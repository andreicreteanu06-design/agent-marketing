"""Inteligenta SEO: agregarea GA4 + Search Console + Keyword Planner si recomandarile.

Serviciul e pur, deci sursele sunt dubluri simple. Se verifica ce ar strica
tacut un grafic sau o recomandare: o medie de rate in loc de o rata a sumelor,
o zi lipsa aratata ca "fara date" cand de fapt a fost zero, o sursa cazuta
inlocuita pe ascuns cu cifre demonstrative, o regula care se declanseaza fara
temei.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

from seo_geo_agent.services.intelligence import (
    DailySearch,
    DailyTraffic,
    IntelligenceData,
    IntelligenceSources,
    PageTraffic,
    QueryStats,
    Window,
    build_intelligence,
    build_keywords,
    build_summary,
    build_timeseries,
    gather,
    generate_insights,
)
from seo_geo_agent.services.intelligence_demo import demo_sources

_END = date(2026, 9, 21)
_WINDOW = Window.ending(_END, 28)


def _rules(data: IntelligenceData) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for insight in generate_insights(data):
        found.setdefault(insight.rule, []).append(insight.subject or "")
    return found


def _traffic(window: Window, sessions: int, engaged: int) -> list[DailyTraffic]:
    return [DailyTraffic(day, sessions, sessions * 2, engaged) for day in window.dates()]


def _search(window: Window, clicks: int, impressions: int, position: float) -> list[DailySearch]:
    return [DailySearch(day, clicks, impressions, position) for day in window.dates()]


# --- ferestre si serie de timp ------------------------------------------------


def test_perioada_anterioara_are_aceeasi_lungime_si_se_termina_inainte() -> None:
    assert (_WINDOW.start, _WINDOW.days) == (date(2026, 8, 25), 28)
    assert _WINDOW.previous == Window(date(2026, 7, 28), date(2026, 8, 24))


def test_o_zi_fara_randuri_e_zero_iar_o_sursa_lipsa_e_fara_date() -> None:
    window = Window.ending(_END, 3)
    data = IntelligenceData(
        window=window,
        traffic_daily=[DailyTraffic(window.start, 100, 180, 60)],
        search_daily=None,
    )
    points = build_timeseries(data)

    assert [point.sessions for point in points] == [100, 0, 0]
    assert points[0].engagement_rate == 0.6
    assert points[1].engagement_rate is None  # 0 sesiuni: rata nedefinita, nu 0%
    assert all(point.clicks is None and point.position is None for point in points)


def test_rata_de_engagement_e_din_sume_nu_media_ratelor_zilnice() -> None:
    """O zi cu 10 sesiuni nu trebuie sa cantareasca cat una cu 1000."""
    days = _WINDOW.dates()
    now = [DailyTraffic(days[0], 1000, 2000, 800), DailyTraffic(days[1], 10, 20, 0)]
    data = IntelligenceData(window=_WINDOW, traffic_daily=now, traffic_daily_prev=now)
    engagement = next(m for m in build_summary(data) if m.key == "engagement_rate")

    assert engagement.value == round(800 / 1010, 4)  # nu (0.8 + 0.0) / 2 = 0.4


def test_pozitia_medie_e_ponderata_cu_afisarile() -> None:
    days = _WINDOW.dates()
    now = [DailySearch(days[0], 10, 900, 2.0), DailySearch(days[1], 0, 100, 40.0)]
    data = IntelligenceData(window=_WINDOW, search_daily=now, search_daily_prev=now)
    position = next(m for m in build_summary(data) if m.key == "position")

    assert position.value == 5.8  # (2*900 + 40*100) / 1000
    assert position.better_when == "down"


def test_evolutia_fata_de_zero_nu_e_un_procent_inventat() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        search_daily=_search(_WINDOW, 5, 100, 8.0),
        search_daily_prev=_search(_WINDOW.previous, 0, 0, 0.0),
    )
    clicks = next(m for m in build_summary(data) if m.key == "clicks")
    assert clicks.change_pct is None


# --- clasamentul cuvintelor -----------------------------------------------------


def test_clasamentul_arata_evolutia_si_volumul_din_keyword_planner() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        queries_now=[
            QueryStats("Schimb ulei", 50, 900, 4.0, page="/ulei"),
            QueryStats("diagnoza auto", 20, 500, 9.0),
            QueryStats("vulcanizare", 90, 1200, 2.2),
            QueryStats("cuvant nou", 1, 40, 30.0),
        ],
        queries_prev=[
            QueryStats("schimb ulei", 40, 800, 7.0),
            QueryStats("diagnoza auto", 30, 600, 5.0),
            QueryStats("vulcanizare", 88, 1150, 2.4),
        ],
        volumes={"schimb ulei": 2400},
    )
    rows = {row.keyword: row for row in build_keywords(data)}

    assert next(row.keyword for row in build_keywords(data)) == "vulcanizare"  # dupa clicuri
    assert (rows["Schimb ulei"].trend, rows["Schimb ulei"].change) == ("up", 3.0)
    assert rows["Schimb ulei"].search_volume == 2400  # potrivire fara majuscule
    assert rows["Schimb ulei"].url == "/ulei"
    assert (rows["diagnoza auto"].trend, rows["diagnoza auto"].change) == ("down", -4.0)
    assert rows["vulcanizare"].trend == "stable"
    assert (rows["cuvant nou"].trend, rows["cuvant nou"].change) == ("new", None)


# --- reguli -------------------------------------------------------------------------


def test_ctr_mic_la_o_pozitie_buna_cere_rescrierea_meta_description() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        queries_now=[
            QueryStats("schimb ulei", 10, 1000, 4.0, page="/ulei"),  # 1% vs ~8%
            QueryStats("revizie", 70, 1000, 4.0),  # 7%: normal
        ],
    )
    insights = [i for i in generate_insights(data) if i.rule == "low_ctr"]

    assert [i.subject for i in insights] == ["schimb ulei"]
    assert insights[0].priority == "high"
    assert "/ulei" in insights[0].action
    assert insights[0].evidence["CTR"] == "1,0%"


def test_cuvintele_de_pe_pagina_a_doua_sunt_oportunitati() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        queries_now=[
            QueryStats("aproape", 5, 600, 13.0),
            QueryStats("deja sus", 80, 600, 2.0),
            QueryStats("prea departe", 0, 600, 35.0),
        ],
    )
    assert _rules(data).get("striking_distance") == ["aproape"]


def test_o_pagina_care_pierde_trafic_da_alerta() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        pages_now=[PageTraffic("/ulei", 300, 200), PageTraffic("/", 950, 600)],
        pages_prev=[
            PageTraffic("/ulei", 600, 400),  # -50%
            PageTraffic("/", 1000, 650),  # -5%: zgomot
            PageTraffic("/mica", 30, 20),  # prea mica sa conteze
        ],
    )
    insights = [i for i in generate_insights(data) if i.rule == "page_traffic_drop"]

    assert [i.subject for i in insights] == ["/ulei"]
    assert (insights[0].kind, insights[0].priority) == ("alert", "high")


def test_un_cuvant_din_top_10_care_coboara_da_alerta() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        queries_now=[QueryStats("diagnoza", 10, 500, 9.0), QueryStats("coada", 1, 300, 25.0)],
        queries_prev=[QueryStats("diagnoza", 60, 500, 4.0), QueryStats("coada", 20, 300, 18.0)],
    )
    assert _rules(data).get("position_drop") == ["diagnoza"]


def test_engagementul_mic_si_cererea_fara_prezenta_sunt_semnalate() -> None:
    data = IntelligenceData(
        window=_WINDOW,
        pages_now=[PageTraffic("/preturi", 400, 100), PageTraffic("/", 400, 260)],
        queries_now=[QueryStats("schimb ulei", 10, 300, 5.0)],
        volumes={"schimb ulei": 2400, "reparatii cutie automata": 2900, "rar": 50},
    )
    rules = _rules(data)

    assert rules.get("low_engagement") == ["/preturi"]
    assert rules.get("content_gap") == ["reparatii cutie automata"]  # "rar": volum prea mic


@pytest.mark.parametrize(("now", "kind", "sign"), [(700, "alert", "-"), (1300, "info", "+")])
def test_tendinta_generala_a_traficului(now: int, kind: str, sign: str) -> None:
    data = IntelligenceData(
        window=_WINDOW,
        traffic_daily=_traffic(_WINDOW, now // 28, 0),
        traffic_daily_prev=_traffic(_WINDOW.previous, 1000 // 28, 0),
    )
    trend = [i for i in generate_insights(data) if i.rule == "overall_trend"]
    assert trend[0].kind == kind
    assert trend[0].evidence["Evoluție"].startswith(sign)


def test_pragurile_se_scaleaza_cu_lungimea_perioadei() -> None:
    """200 de afisari inseamna altceva in 7 zile decat in 90."""
    weak_ctr = [QueryStats("schimb ulei", 1, 120, 4.0)]
    week = IntelligenceData(window=Window.ending(_END, 7), queries_now=weak_ctr)
    quarter = IntelligenceData(window=Window.ending(_END, 90), queries_now=weak_ctr)

    assert "low_ctr" in _rules(week)
    assert "low_ctr" not in _rules(quarter)


def test_fara_date_nu_exista_recomandari() -> None:
    assert generate_insights(IntelligenceData(window=_WINDOW)) == []


# --- colectare --------------------------------------------------------------------


@dataclass
class _Search:
    fail: bool = False
    calls: list[Window] = field(default_factory=list)

    def daily(self, window: Window) -> list[DailySearch]:
        self.calls.append(window)
        if self.fail:
            raise RuntimeError("Search Console refuza accesul")
        return _search(window, 10, 200, 6.0)

    def queries(self, window: Window) -> list[QueryStats]:
        return [QueryStats("schimb ulei", 10, 200, 6.0)]


@dataclass
class _Analytics:
    def daily(self, window: Window) -> list[DailyTraffic]:
        return _traffic(window, 50, 30)

    def pages(self, window: Window) -> list[PageTraffic]:
        return [PageTraffic("/", 50 * window.days, 30 * window.days)]


def test_o_sursa_cazuta_ramane_goala_nu_devine_demo() -> None:
    """Cifre demonstrative in locul datelor reale ar fi o minciuna in raportul clientului."""
    sources = IntelligenceSources(
        analytics=_Analytics(),
        analytics_status="live",
        search=_Search(fail=True),
        search_status="live",
    )
    payload = build_intelligence(sources, domain="exemplu.ro", window=_WINDOW)
    states = {state.key: state.status for state in payload.sources}

    assert states["gsc"] == "unavailable"
    assert states["ga4"] == "live"
    assert payload.is_demo is False
    assert payload.data_gaps == ["Google Search Console: Search Console refuza accesul"]
    assert all(point.clicks is None for point in payload.timeseries)
    assert payload.timeseries[0].sessions == 50
    assert payload.keywords == []


def test_perioada_curenta_si_cea_anterioara_se_cer_amandoua() -> None:
    search = _Search()
    gather(
        IntelligenceSources(
            analytics=None, analytics_status="not_connected", search=search, search_status="live"
        ),
        _WINDOW,
    )
    assert search.calls == [_WINDOW, _WINDOW.previous]


# --- date demonstrative -------------------------------------------------------------


def test_datele_demo_sunt_marcate_si_deterministe() -> None:
    first = build_intelligence(
        demo_sources("https://www.artingauto.ro", _END + timedelta(days=3)),
        domain="www.artingauto.ro",
        window=_WINDOW,
    )
    again = build_intelligence(
        demo_sources("https://www.artingauto.ro", _END + timedelta(days=3)),
        domain="www.artingauto.ro",
        window=_WINDOW,
    )

    assert first.is_demo is True
    assert {state.status for state in first.sources} == {"demo"}
    assert first.timeseries == again.timeseries
    assert first.keywords == again.keywords


def test_o_zi_demo_are_aceleasi_cifre_in_orice_fereastra() -> None:
    """Altfel graficul de 7 zile si cel de 28 ar arata alt trafic pentru aceeasi zi."""
    sources = demo_sources("exemplu.ro", _END)
    week = build_intelligence(sources, domain="exemplu.ro", window=Window.ending(_END, 7))
    month = build_intelligence(sources, domain="exemplu.ro", window=Window.ending(_END, 28))
    assert week.timeseries == month.timeseries[-7:]


def test_datele_demo_arata_fiecare_tip_de_recomandare() -> None:
    payload = build_intelligence(
        demo_sources("https://www.artingauto.ro", _END + timedelta(days=3)),
        domain="www.artingauto.ro",
        window=_WINDOW,
    )
    rules = {insight.rule for insight in payload.ai_recommendations}
    assert {
        "low_ctr",
        "page_traffic_drop",
        "position_drop",
        "striking_distance",
        "low_engagement",
        "content_gap",
    } <= rules
    assert payload.model_dump_json()  # serializabil pentru API


# --- intrebari fara click-uri (question_gap) ----------------------------------------


def _questions(*queries: QueryStats) -> IntelligenceData:
    """Cuvintele date, plus cateva mici care coboara media afisarilor site-ului."""
    filler = [QueryStats(f"cuvant {index}", 5, 100, 12.0) for index in range(6)]
    return IntelligenceData(window=_WINDOW, queries_now=[*queries, *filler])


@pytest.mark.parametrize(
    "query",
    [
        "cand se schimba uleiul la cutia automata",
        "Când se schimbă uleiul",
        "de ce scartaie franele",
        "cât costă revizia",
        "care e pretul unei revizii",
    ],
)
def test_intrebarile_la_care_apari_sus_fara_clicuri_sunt_oportunitati(query: str) -> None:
    data = _questions(QueryStats(query, 10, 2000, 5.5, page="/ulei"))
    insights = [i for i in generate_insights(data) if i.rule == "question_gap"]

    assert [i.subject for i in insights] == [query]
    insight = insights[0]
    assert insight.priority == "high"
    assert insight.title == (
        f"Oportunitate de conținut: Răspunde mai bine la întrebarea «{query}»"
    )
    assert insight.detail.startswith(
        "Pagina ta apare pe poziția 5,5 și a fost afișată de 2.000 de ori, dar primește doar "
        "10 click-uri (CTR 0,5%)."
    )
    assert insight.action.startswith("Revizuiește pagina /ulei. Analizează top 3 concurenți")


@pytest.mark.parametrize(
    ("query", "motiv"),
    [
        (QueryStats("carena auto pret", 10, 2000, 5.5), "nu e intrebare, doar incepe la fel"),
        (QueryStats("schimb ulei ce pret", 10, 2000, 5.5), "cuvantul interogativ nu e primul"),
        (QueryStats("cand se schimba uleiul", 10, 2000, 12.0), "pozitie peste 10"),
        (QueryStats("cand se schimba uleiul", 60, 2000, 5.5), "CTR 3%: primeste click-uri"),
        # 60 < media de ~94, dar peste pragul minim: exclusa doar de conditia de medie.
        (QueryStats("cand se schimba uleiul", 0, 60, 5.5), "afisari sub media site-ului"),
    ],
)
def test_regula_de_intrebari_cere_toate_cele_trei_conditii(query: QueryStats, motiv: str) -> None:
    assert "question_gap" not in _rules(_questions(query)), motiv


def test_intrebarile_sunt_luate_in_ordinea_afisarilor() -> None:
    data = _questions(
        QueryStats("cum aleg uleiul", 5, 1500, 4.0),
        QueryStats("cand se schimba uleiul", 0, 3000, 6.0),
    )
    assert _rules(data)["question_gap"] == ["cand se schimba uleiul", "cum aleg uleiul"]


def test_o_intrebare_fara_niciun_click_si_fara_pagina_cunoscuta() -> None:
    data = _questions(QueryStats("cand se schimba uleiul", 0, 3000, 6.0))
    (insight,) = [i for i in generate_insights(data) if i.rule == "question_gap"]
    assert "dar nu primește click-uri." in insight.detail
    assert insight.action.startswith("Revizuiește pagina care apare în Google pentru această")


def test_intrebarea_nu_apare_de_doua_ori_si_ca_ctr_mic() -> None:
    """La pozitia 4 si CTR 0,5% s-ar declansa si "CTR mic" - o singura sarcina, nu doua."""
    data = _questions(QueryStats("cand se schimba uleiul", 10, 2000, 4.0))
    rules = _rules(data)
    assert rules["question_gap"] == ["cand se schimba uleiul"]
    assert "cand se schimba uleiul" not in rules.get("low_ctr", [])


def test_datele_demo_arata_regula_de_intrebari() -> None:
    payload = build_intelligence(
        demo_sources("https://www.artingauto.ro", _END + timedelta(days=3)),
        domain="www.artingauto.ro",
        window=_WINDOW,
    )
    questions = [i for i in payload.ai_recommendations if i.rule == "question_gap"]
    assert questions
    assert all(i.subject and i.subject.startswith(("cand", "cat")) for i in questions)
    # Intrebarea de pe pagina 2 din demo nu intra in regula.
    assert "ce ulei pentru cutie automata" not in {i.subject for i in questions}
