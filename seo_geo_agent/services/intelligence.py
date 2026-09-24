"""Inteligenta SEO: triangularea GA4 + Search Console + Keyword Planner.

Trei surse, trei intrebari diferite:

- **GA4** - ce fac vizitatorii: sesiuni, vizualizari, engagement; pe zi si pe pagina.
- **Search Console** - cum te vede Google: clicuri, afisari, pozitie; pe zi si pe cuvant.
- **Keyword Planner** - cat se cauta un cuvant, indiferent daca apari sau nu la el.

Modulul e pur: nu stie de unde vin datele. Sursele sunt protocoale, implementate
de adaptoarele live (``ppc_agent_server/seo_intelligence.py``, peste token-urile
OAuth ale clientului) si de sursa demonstrativa (``intelligence_demo.py``).

Recomandarile (``ai_recommendations``) sunt reguli verificabile, nu parerea
unui model: fiecare vine cu cifrele care au declansat-o, in ``evidence``. Un
client care prinde o recomandare fara temei nu le mai crede nici pe celelalte.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("seo_geo_agent.services.intelligence")

_T = TypeVar("_T")

INTELLIGENCE_VERSION: Literal[1] = 1

SourceKey = Literal["ga4", "gsc", "keyword_planner"]
#: live = datele reale ale clientului; demo = date demonstrative (sursa neconectata);
#: not_connected = fara date si fara demo; unavailable = conectata, dar a picat acum.
SourceStatus = Literal["live", "demo", "not_connected", "unavailable"]
MetricKey = Literal[
    "sessions", "pageviews", "engagement_rate", "clicks", "impressions", "ctr", "position"
]

#: CTR-ul obisnuit pe pozitiile 1-10 din rezultatele organice (medii publice,
#: rotunjite). Referinta pentru "CTR mic": sub jumatate din asta, la pozitia ta,
#: titlul si descrierea nu conving.
EXPECTED_CTR: dict[int, float] = {
    1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.065,
    6: 0.05, 7: 0.04, 8: 0.033, 9: 0.028, 10: 0.025,
}
#: Cate recomandari pe regula si in total - peste, lista nu se mai citeste.
_PER_RULE = 3
_MAX_INSIGHTS = 10
#: Cate cuvinte intra in clasament.
_MAX_KEYWORDS = 50


# --- Ferestre de timp --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Window:
    """Un interval de zile inclusiv la ambele capete."""

    start: date
    end: date

    @classmethod
    def ending(cls, end: date, days: int) -> Window:
        return cls(start=end - timedelta(days=days - 1), end=end)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> Window:
        """Aceeasi lungime, imediat inainte - baza oricarei comparatii."""
        return Window.ending(self.start - timedelta(days=1), self.days)

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.days)]


# --- Ce primeste serviciul de la surse ----------------------------------------


@dataclass(frozen=True, slots=True)
class DailyTraffic:
    """O zi din GA4. ``engaged_sessions``, nu rata: ratele nu se aduna corect."""

    day: date
    sessions: int
    pageviews: int
    engaged_sessions: int


@dataclass(frozen=True, slots=True)
class PageTraffic:
    """O pagina din GA4, agregata pe un interval."""

    path: str
    sessions: int
    engaged_sessions: int


@dataclass(frozen=True, slots=True)
class DailySearch:
    """O zi din Search Console. ``position`` e media ponderata cu afisarile."""

    day: date
    clicks: int
    impressions: int
    position: float


@dataclass(frozen=True, slots=True)
class QueryStats:
    """Un cuvant din Search Console, agregat pe un interval."""

    query: str
    clicks: int
    impressions: int
    position: float
    #: Pagina care apare cel mai des pentru cuvant, daca sursa o stie.
    page: str = ""


class AnalyticsSource(Protocol):
    """GA4: trafic pe zi si pe pagina."""

    def daily(self, window: Window) -> list[DailyTraffic]: ...

    def pages(self, window: Window) -> list[PageTraffic]: ...


class SearchSource(Protocol):
    """Search Console: vizibilitate pe zi si pe cuvant."""

    def daily(self, window: Window) -> list[DailySearch]: ...

    def queries(self, window: Window) -> list[QueryStats]: ...


class VolumeSource(Protocol):
    """Keyword Planner: volumul lunar pentru cuvintele date si pentru idei inrudite."""

    def volumes(self, seeds: list[str]) -> dict[str, int]: ...


@dataclass(slots=True)
class IntelligenceSources:
    """Sursele unui client si starea fiecareia, decisa de cine le construieste."""

    analytics: AnalyticsSource | None
    analytics_status: SourceStatus
    search: SearchSource | None
    search_status: SourceStatus
    volumes: VolumeSource | None = None
    volumes_status: SourceStatus = "not_connected"
    #: De ce e o sursa in starea ei (ex. "Conecteaza GA4 din Integrari").
    notes: dict[SourceKey, str] = field(default_factory=dict)


# --- Ce trimite serviciul catre interfata -------------------------------------


class ReportPeriod(BaseModel):
    start: date
    end: date
    days: int


class SourceState(BaseModel):
    key: SourceKey
    label: str
    status: SourceStatus
    note: str | None = None


class TimeSeriesPoint(BaseModel):
    """O zi pe grafic. ``None`` = sursa nu are date, nu "zero"."""

    date: date
    sessions: int | None
    pageviews: int | None
    engagement_rate: float | None
    clicks: int | None
    impressions: int | None
    ctr: float | None
    position: float | None


class MetricSummary(BaseModel):
    """Un indicator al perioadei, fata de perioada anterioara."""

    key: MetricKey
    label: str
    source: Literal["ga4", "gsc"]
    value: float | None
    previous: float | None
    change_pct: float | None
    #: Pozitia e mai buna cand SCADE - interfata coloreaza evolutia dupa asta.
    better_when: Literal["up", "down"]
    format: Literal["number", "percent", "position"]


class KeywordRank(BaseModel):
    """Un rand din clasamentul cuvintelor cheie."""

    keyword: str
    position: float
    previous_position: float | None
    #: Pozitii castigate (pozitiv = a urcat). ``None`` la cuvintele noi.
    change: float | None
    trend: Literal["up", "down", "stable", "new"]
    clicks: int
    impressions: int
    ctr: float
    search_volume: int | None
    url: str | None


class SeoInsight(BaseModel):
    """O recomandare, cu cifrele care au declansat-o."""

    id: str
    rule: str
    kind: Literal["alert", "opportunity", "info"]
    priority: Literal["high", "medium", "low"]
    title: str
    detail: str
    action: str
    #: Cifrele-dovada, deja formatate pentru afisare ("CTR": "0,9%").
    evidence: dict[str, str]
    subject: str | None = None


class SEOIntelligencePayload(BaseModel):
    """Tot ce afiseaza pagina "Trafic & Pozitii", intr-un singur raspuns."""

    version: Literal[1] = INTELLIGENCE_VERSION
    domain: str
    period: ReportPeriod
    previous_period: ReportPeriod
    generated_at: datetime
    #: Adevarat daca cel putin o sursa afisata e demonstrativa.
    is_demo: bool
    sources: list[SourceState]
    summary: list[MetricSummary]
    timeseries: list[TimeSeriesPoint]
    keywords: list[KeywordRank]
    ai_recommendations: list[SeoInsight]
    recommendations_engine: Literal["rules"] = "rules"
    data_gaps: list[str]


# --- Colectare -----------------------------------------------------------------


@dataclass(slots=True)
class IntelligenceData:
    """Datele adunate; ``None`` pe o lista = sursa lipseste sau a picat."""

    window: Window
    traffic_daily: list[DailyTraffic] | None = None
    traffic_daily_prev: list[DailyTraffic] | None = None
    pages_now: list[PageTraffic] | None = None
    pages_prev: list[PageTraffic] | None = None
    search_daily: list[DailySearch] | None = None
    search_daily_prev: list[DailySearch] | None = None
    queries_now: list[QueryStats] | None = None
    queries_prev: list[QueryStats] | None = None
    volumes: dict[str, int] = field(default_factory=dict)


_SOURCE_LABELS: dict[SourceKey, str] = {
    "ga4": "Google Analytics 4",
    "gsc": "Google Search Console",
    "keyword_planner": "Google Keyword Planner",
}


def _attempt(label: str, gaps: list[str], call: Callable[[], _T]) -> tuple[_T | None, bool]:
    """Apeleaza o sursa; o eroare devine un gol de date, nu un raport picat."""
    try:
        return call(), True
    except Exception as exc:
        logger.warning("sursa %s a esuat: %s", label, exc)
        gaps.append(f"{label}: {exc}")
        return None, False


def gather(
    sources: IntelligenceSources, window: Window
) -> tuple[IntelligenceData, list[SourceState], list[str]]:
    """Aduna datele celor trei surse pentru ``window`` si perioada anterioara.

    O sursa care pica nu opreste raportul si NU e inlocuita cu date demo: ar
    arata cifre inventate ca si cum ar fi ale clientului. Ramane goala, cu
    motivul in ``data_gaps``.
    """
    data = IntelligenceData(window=window)
    gaps: list[str] = []
    statuses: dict[SourceKey, SourceStatus] = {
        "ga4": sources.analytics_status,
        "gsc": sources.search_status,
        "keyword_planner": sources.volumes_status,
    }

    analytics = sources.analytics
    if analytics is not None:
        label = _SOURCE_LABELS["ga4"]
        daily, ok_daily = _attempt(label, gaps, lambda: analytics.daily(window))
        prev, ok_prev = _attempt(label, gaps, lambda: analytics.daily(window.previous))
        pages, ok_pages = _attempt(label, gaps, lambda: analytics.pages(window))
        pages_prev, ok_pages_prev = _attempt(label, gaps, lambda: analytics.pages(window.previous))
        if ok_daily and ok_prev and ok_pages and ok_pages_prev:
            data.traffic_daily, data.traffic_daily_prev = daily, prev
            data.pages_now, data.pages_prev = pages, pages_prev
        else:
            statuses["ga4"] = "unavailable"

    search = sources.search
    if search is not None:
        label = _SOURCE_LABELS["gsc"]
        s_daily, ok_daily = _attempt(label, gaps, lambda: search.daily(window))
        s_prev, ok_prev = _attempt(label, gaps, lambda: search.daily(window.previous))
        q_now, ok_q = _attempt(label, gaps, lambda: search.queries(window))
        q_prev, ok_q_prev = _attempt(label, gaps, lambda: search.queries(window.previous))
        if ok_daily and ok_prev and ok_q and ok_q_prev:
            data.search_daily, data.search_daily_prev = s_daily, s_prev
            data.queries_now, data.queries_prev = q_now, q_prev
        else:
            statuses["gsc"] = "unavailable"

    volumes = sources.volumes
    if volumes is not None:
        seeds = [query.query for query in (data.queries_now or [])[:_MAX_KEYWORDS]]
        found, ok = _attempt(
            _SOURCE_LABELS["keyword_planner"], gaps, lambda: volumes.volumes(seeds)
        )
        if ok and found is not None:
            data.volumes = {keyword.lower(): volume for keyword, volume in found.items()}
        else:
            statuses["keyword_planner"] = "unavailable"

    states = [
        SourceState(key=key, label=_SOURCE_LABELS[key], status=status, note=sources.notes.get(key))
        for key, status in statuses.items()
    ]
    # Deduplicat: aceeasi eroare vine de la fiecare cerere a sursei.
    return data, states, list(dict.fromkeys(gaps))


# --- Transformari ---------------------------------------------------------------


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    """Evolutia in procente; ``None`` fata de zero sau fara date (nu "+100%")."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _weighted_position(rows: Iterable[DailySearch]) -> float | None:
    rows = list(rows)
    impressions = sum(row.impressions for row in rows)
    if impressions == 0:
        return None
    return round(sum(row.position * row.impressions for row in rows) / impressions, 1)


def build_timeseries(data: IntelligenceData) -> list[TimeSeriesPoint]:
    """Cate un punct pe zi. O zi fara randuri, la o sursa prezenta, e zero, nu gaura."""
    traffic = {row.day: row for row in data.traffic_daily or []}
    search = {row.day: row for row in data.search_daily or []}
    has_traffic = data.traffic_daily is not None
    has_search = data.search_daily is not None
    points: list[TimeSeriesPoint] = []
    for day in data.window.dates():
        t = traffic.get(day)
        s = search.get(day)
        sessions = t.sessions if t else 0
        clicks = s.clicks if s else 0
        impressions = s.impressions if s else 0
        engagement = _ratio(t.engaged_sessions, t.sessions) if t else None
        engagement = round(engagement, 4) if has_traffic and engagement is not None else None
        ctr = _ratio(clicks, impressions)
        points.append(
            TimeSeriesPoint(
                date=day,
                sessions=sessions if has_traffic else None,
                pageviews=(t.pageviews if t else 0) if has_traffic else None,
                engagement_rate=engagement,
                clicks=clicks if has_search else None,
                impressions=impressions if has_search else None,
                ctr=round(ctr, 4) if has_search and ctr is not None else None,
                position=round(s.position, 1) if has_search and s and s.impressions else None,
            )
        )
    return points


def build_summary(data: IntelligenceData) -> list[MetricSummary]:
    """Indicatorii perioadei, fiecare fata de perioada anterioara."""
    summary: list[MetricSummary] = []

    def add(
        key: MetricKey,
        label: str,
        source: Literal["ga4", "gsc"],
        now: float | None,
        before: float | None,
        better_when: Literal["up", "down"] = "up",
        fmt: Literal["number", "percent", "position"] = "number",
    ) -> None:
        summary.append(
            MetricSummary(
                key=key,
                label=label,
                source=source,
                value=now,
                previous=before,
                change_pct=_pct_change(now, before),
                better_when=better_when,
                format=fmt,
            )
        )

    if data.traffic_daily is not None and data.traffic_daily_prev is not None:
        now_t, prev_t = data.traffic_daily, data.traffic_daily_prev
        sessions, sessions_prev = sum(r.sessions for r in now_t), sum(r.sessions for r in prev_t)
        add("sessions", "Sesiuni", "ga4", sessions, sessions_prev)
        pageviews = sum(r.pageviews for r in now_t)
        add("pageviews", "Vizualizări", "ga4", pageviews, sum(r.pageviews for r in prev_t))
        rate_now = _ratio(sum(r.engaged_sessions for r in now_t), sessions)
        rate_prev = _ratio(sum(r.engaged_sessions for r in prev_t), sessions_prev)
        add(
            "engagement_rate",
            "Rată de engagement",
            "ga4",
            round(rate_now, 4) if rate_now is not None else None,
            round(rate_prev, 4) if rate_prev is not None else None,
            fmt="percent",
        )

    if data.search_daily is not None and data.search_daily_prev is not None:
        now_s, prev_s = data.search_daily, data.search_daily_prev
        clicks, clicks_prev = sum(r.clicks for r in now_s), sum(r.clicks for r in prev_s)
        impressions = sum(r.impressions for r in now_s)
        impressions_prev = sum(r.impressions for r in prev_s)
        add("clicks", "Clicuri din Google", "gsc", clicks, clicks_prev)
        add("impressions", "Afișări în Google", "gsc", impressions, impressions_prev)
        ctr_now, ctr_prev = _ratio(clicks, impressions), _ratio(clicks_prev, impressions_prev)
        add(
            "ctr",
            "CTR",
            "gsc",
            round(ctr_now, 4) if ctr_now is not None else None,
            round(ctr_prev, 4) if ctr_prev is not None else None,
            fmt="percent",
        )
        add(
            "position",
            "Poziție medie",
            "gsc",
            _weighted_position(now_s),
            _weighted_position(prev_s),
            better_when="down",
            fmt="position",
        )
    return summary


def build_keywords(data: IntelligenceData) -> list[KeywordRank]:
    """Clasamentul (stil Ahrefs): pozitia de acum, cea de dinainte si traficul adus."""
    if data.queries_now is None:
        return []
    previous = {row.query.lower(): row for row in data.queries_prev or []}
    ranked = sorted(data.queries_now, key=lambda row: (-row.clicks, -row.impressions))
    rows: list[KeywordRank] = []
    for query in ranked[:_MAX_KEYWORDS]:
        before = previous.get(query.query.lower())
        position = round(query.position, 1)
        change: float | None
        trend: Literal["up", "down", "stable", "new"]
        if before is None:
            change, trend = None, "new"
        else:
            change = round(before.position - query.position, 1)
            trend = "stable" if abs(change) < 0.5 else ("up" if change > 0 else "down")
        rows.append(
            KeywordRank(
                keyword=query.query,
                position=position,
                previous_position=round(before.position, 1) if before else None,
                change=change,
                trend=trend,
                clicks=query.clicks,
                impressions=query.impressions,
                ctr=round(query.clicks / query.impressions, 4) if query.impressions else 0.0,
                search_volume=data.volumes.get(query.query.lower()),
                url=query.page or None,
            )
        )
    return rows


# --- Recomandari (reguli) ----------------------------------------------------------


def _int(value: float) -> str:
    """``4820`` -> ``4.820`` (separator de mii romanesc)."""
    return f"{round(value):,}".replace(",", ".")


def _dec(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(ratio: float, digits: int = 1) -> str:
    return f"{_dec(ratio * 100, digits)}%"


def _count(value: int, plural: str) -> str:
    """ "9 click-uri", "39 de click-uri": de la 20 in sus (si la sutele rotunde) se cere "de"."""
    rest = value % 100
    return f"{_int(value)} {'de ' if value and (rest == 0 or rest >= 20) else ''}{plural}"


def _page_label(path: str) -> str:
    return path or "pagina"


def _expected_ctr(position: float) -> float | None:
    return EXPECTED_CTR.get(max(1, round(position)))


#: Interogarile-intrebare: incep cu un cuvant interogativ, cu sau fara diacritice.
#: ``\b`` le separa de cuvintele care doar incep la fel ("carena", "catalog", "cea").
QUESTION_PATTERN = re.compile(
    r"^(de ce|ce|cum|cand|când|unde|cat|cât|cate|câte|cati|câți|care|cine)\b", re.IGNORECASE
)
#: Sub acest CTR, o intrebare afisata sus practic nu primeste click-uri.
_QUESTION_MAX_CTR = 0.02


def is_question(query: str) -> bool:
    """Adevarat daca interogarea e o intrebare ("cand se schimba uleiul ...")."""
    return QUESTION_PATTERN.match(query.strip()) is not None


def _rule_question_gap(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Intrebari la care Google te arata sus, dar oamenii nu dau click.

    Toate trei deodata: afisari peste media cuvintelor site-ului, CTR sub 2% si
    pozitie sub 10. Google considera pagina relevanta pentru intrebare, dar
    fragmentul din rezultate nu promite raspunsul - de obicei pagina nici nu il
    da direct. Pragul minim de afisari (scalat cu perioada) opreste regula sa
    se declanseze pe cateva afisari intamplatoare la un site mic.
    """
    queries = data.queries_now or []
    if not queries:
        return []
    average = sum(query.impressions for query in queries) / len(queries)
    questions = sorted(
        (query for query in queries if is_question(query.query)),
        key=lambda query: -query.impressions,
    )
    found: list[SeoInsight] = []
    for query in questions:
        ctr = query.clicks / query.impressions if query.impressions else 0.0
        if (
            query.impressions <= average
            or query.impressions < max(20, 50 * scale)
            or ctr >= _QUESTION_MAX_CTR
            or not 0 < query.position < 10
        ):
            continue
        if query.clicks == 0:
            clicks = "nu primește click-uri"
        elif query.clicks == 1:
            clicks = f"primește un singur click (CTR {_pct(ctr)})"
        else:
            clicks = f"primește doar {_count(query.clicks, 'click-uri')} (CTR {_pct(ctr)})"
        page = query.page or "care apare în Google pentru această întrebare"
        found.append(
            SeoInsight(
                id=f"question_gap:{query.query}",
                rule="question_gap",
                kind="opportunity",
                priority="high",
                title=f"Oportunitate de conținut: Răspunde mai bine la întrebarea «{query.query}»",
                detail=(
                    f"Pagina ta apare pe poziția {_dec(query.position)} și a fost afișată de "
                    f"{_count(query.impressions, 'ori')}, dar {clicks}. Google consideră că "
                    "pagina ta e relevantă, dar utilizatorii nu găsesc răspunsul dorit."
                ),
                action=(
                    f"Revizuiește pagina {page}. Analizează top 3 concurenți pentru această "
                    "întrebare. Adaugă un paragraf sau o secțiune de FAQ care să răspundă "
                    "direct și clar la această întrebare, folosind experiența ta reală."
                ),
                evidence={
                    "Poziție": _dec(query.position),
                    "Afișări": _int(query.impressions),
                    "Media site-ului": _int(average),
                    "Clicuri": _int(query.clicks),
                    "CTR": _pct(ctr),
                },
                subject=query.query,
            )
        )
        if len(found) == _PER_RULE:
            break
    return found


def _rule_low_ctr(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Multe afisari, pozitie buna, putine clicuri: titlul si descrierea nu conving."""
    found: list[tuple[float, SeoInsight]] = []
    for query in data.queries_now or []:
        expected = _expected_ctr(query.position)
        if expected is None or query.impressions < max(50, 200 * scale):
            continue
        actual = query.clicks / query.impressions
        if actual >= expected * 0.5:
            continue
        missed = query.impressions * (expected - actual)
        page = _page_label(query.page)
        found.append(
            (
                missed,
                SeoInsight(
                    id=f"low_ctr:{query.query}",
                    rule="low_ctr",
                    kind="opportunity",
                    priority="high" if missed >= 50 * scale else "medium",
                    title=f"CTR mic la „{query.query}”",
                    detail=(
                        f"Apari pe poziția {_dec(query.position)} cu {_int(query.impressions)} "
                        f"afișări, dar doar {_pct(actual)} dau click. La poziția asta, "
                        f"~{_pct(expected, 0)} e obișnuit."
                    ),
                    action=(
                        f"Rescrie title-ul și meta description pentru {page}: pune „{query.query}” "
                        "la început, un beneficiu concret și un îndemn clar. Potențial: "
                        f"~{_int(missed)} clicuri în plus pe {data.window.days} zile."
                    ),
                    evidence={
                        "Afișări": _int(query.impressions),
                        "CTR": _pct(actual),
                        "CTR obișnuit": f"~{_pct(expected, 0)}",
                        "Poziție": _dec(query.position),
                    },
                    subject=query.query,
                ),
            )
        )
    found.sort(key=lambda item: -item[0])
    return [insight for _, insight in found[:_PER_RULE]]


def _rule_striking_distance(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Pozitia 8-20: cel mai ieftin trafic de castigat e cel aproape de prima pagina."""
    found: list[tuple[int, SeoInsight]] = []
    for query in data.queries_now or []:
        if not 8 <= query.position <= 20 or query.impressions < max(30, 100 * scale):
            continue
        volume = data.volumes.get(query.query.lower())
        on_page_two = query.position > 10.5
        evidence = {"Poziție": _dec(query.position), "Afișări": _int(query.impressions)}
        if volume:
            evidence["Căutări lunare"] = _int(volume)
        found.append(
            (
                volume or query.impressions,
                SeoInsight(
                    id=f"striking_distance:{query.query}",
                    rule="striking_distance",
                    kind="opportunity",
                    priority="medium",
                    title=(
                        f"„{query.query}” e la un pas de prima pagină"
                        if on_page_two
                        else f"„{query.query}” e la limita primei pagini"
                    ),
                    detail=(
                        f"Poziția medie {_dec(query.position)}, cu {_int(query.impressions)} "
                        "afișări. Sub locul 10 aproape nimeni nu dă click; câteva poziții în "
                        "plus înseamnă trafic care acum se duce la concurență."
                    ),
                    action=(
                        f"Întărește {_page_label(query.page)}: o secțiune dedicată "
                        f"„{query.query}”, întrebări frecvente și link-uri interne cu acest "
                        "text de pe paginile tale cu trafic."
                    ),
                    evidence=evidence,
                    subject=query.query,
                ),
            )
        )
    found.sort(key=lambda item: -item[0])
    return [insight for _, insight in found[:_PER_RULE]]


def _rule_page_traffic_drop(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """O pagina importanta pierde trafic - de aflat de ce, inainte sa conteze in vanzari."""
    if data.pages_now is None or data.pages_prev is None:
        return []
    now = {page.path: page for page in data.pages_now}
    found: list[tuple[int, SeoInsight]] = []
    for before in data.pages_prev:
        if before.sessions < max(20, 100 * scale):
            continue
        current = now.get(before.path)
        sessions = current.sessions if current else 0
        change = _pct_change(sessions, before.sessions)
        if change is None or change > -30:
            continue
        lost = before.sessions - sessions
        found.append(
            (
                lost,
                SeoInsight(
                    id=f"page_traffic_drop:{before.path}",
                    rule="page_traffic_drop",
                    kind="alert",
                    priority="high" if change <= -50 else "medium",
                    title=f"Trafic în scădere pe {_page_label(before.path)}",
                    detail=(
                        f"{_int(sessions)} sesiuni în ultimele {data.window.days} zile, față de "
                        f"{_int(before.sessions)} în perioada anterioară ({_dec(change)}%)."
                    ),
                    action=(
                        "Verifică în Search Console dacă pagina a pierdut poziții sau "
                        "afișări, dacă i s-a schimbat conținutul ori titlul și dacă mai e indexată."
                    ),
                    evidence={
                        "Sesiuni acum": _int(sessions),
                        "Înainte": _int(before.sessions),
                        "Evoluție": f"{_dec(change)}%",
                    },
                    subject=before.path,
                ),
            )
        )
    found.sort(key=lambda item: -item[0])
    return [insight for _, insight in found[:_PER_RULE]]


def _rule_position_drop(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Un cuvant care aducea trafic a coborat cateva pozitii."""
    if data.queries_now is None or data.queries_prev is None:
        return []
    now = {query.query.lower(): query for query in data.queries_now}
    found: list[tuple[int, SeoInsight]] = []
    for before in data.queries_prev:
        current = now.get(before.query.lower())
        if current is None or before.position > 10 or before.clicks < max(5, 10 * scale):
            continue
        lost_positions = current.position - before.position
        if lost_positions < 3:
            continue
        found.append(
            (
                before.clicks - current.clicks,
                SeoInsight(
                    id=f"position_drop:{before.query}",
                    rule="position_drop",
                    kind="alert",
                    priority="high" if current.position > 10 else "medium",
                    title=f"„{before.query}” a coborât în Google",
                    detail=(
                        f"De pe poziția {_dec(before.position)} pe {_dec(current.position)}; "
                        f"clicurile au trecut de la {_int(before.clicks)} "
                        f"la {_int(current.clicks)}."
                    ),
                    action=(
                        f"Compară {_page_label(current.page)} cu primele rezultate de acum pentru "
                        f"„{before.query}”: ce acoperă ele și tu nu. Verifică și dacă pagina a "
                        "fost modificată recent."
                    ),
                    evidence={
                        "Poziție acum": _dec(current.position),
                        "Înainte": _dec(before.position),
                        "Clicuri acum": _int(current.clicks),
                    },
                    subject=before.query,
                ),
            )
        )
    found.sort(key=lambda item: -item[0])
    return [insight for _, insight in found[:_PER_RULE]]


def _rule_low_engagement(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Vizitatori care pleaca repede: pagina nu raspunde la ce cautau."""
    found: list[tuple[int, SeoInsight]] = []
    for page in data.pages_now or []:
        rate = _ratio(page.engaged_sessions, page.sessions)
        if rate is None or page.sessions < max(30, 100 * scale) or rate >= 0.4:
            continue
        found.append(
            (
                page.sessions,
                SeoInsight(
                    id=f"low_engagement:{page.path}",
                    rule="low_engagement",
                    kind="opportunity",
                    priority="medium" if rate < 0.3 else "low",
                    title=f"Vizitatorii pleacă repede de pe {_page_label(page.path)}",
                    detail=(
                        f"Doar {_pct(rate, 0)} din {_int(page.sessions)} sesiuni sunt „engaged” "
                        "(peste 10 secunde, o conversie sau cel puțin 2 pagini văzute)."
                    ),
                    action=(
                        "Pune mai sus ce caută oamenii care ajung aici (preț, program, cum te "
                        "contactează) și verifică viteza paginii pe telefon."
                    ),
                    evidence={"Sesiuni": _int(page.sessions), "Engagement": _pct(rate, 0)},
                    subject=page.path,
                ),
            )
        )
    found.sort(key=lambda item: -item[0])
    return [insight for _, insight in found[:_PER_RULE]]


def _rule_content_gap(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Keyword Planner vede cerere acolo unde Search Console nu vede site-ul deloc."""
    if not data.volumes or data.queries_now is None:
        return []
    present = {query.query.lower() for query in data.queries_now}
    gaps = sorted(
        (
            (keyword, volume)
            for keyword, volume in data.volumes.items()
            if keyword not in present and volume >= 100
        ),
        key=lambda item: -item[1],
    )
    return [
        SeoInsight(
            id=f"content_gap:{keyword}",
            rule="content_gap",
            kind="opportunity",
            priority="medium" if volume >= 1000 else "low",
            title=f"Se caută „{keyword}”, dar nu apari",
            detail=(
                f"~{_int(volume)} căutări lunare în Google (Keyword Planner), iar site-ul nu "
                "are nicio afișare la acest cuvânt în Search Console."
            ),
            action=(
                "Creează sau extinde o pagină dedicată. Până urcă organic, cuvântul poate fi "
                "acoperit cu reclame - agentul PPC îl vede în aceleași date."
            ),
            evidence={"Căutări lunare": _int(volume), "Afișări": "0"},
            subject=keyword,
        )
        for keyword, volume in gaps[:_PER_RULE]
    ]


def _rule_overall_trend(data: IntelligenceData, scale: float) -> list[SeoInsight]:
    """Tendinta intregului site: sesiunile GA4 sau, fara GA4, clicurile din Google."""
    if data.traffic_daily is not None and data.traffic_daily_prev is not None:
        now = sum(row.sessions for row in data.traffic_daily)
        before = sum(row.sessions for row in data.traffic_daily_prev)
        metric = "sesiunile"
    elif data.search_daily is not None and data.search_daily_prev is not None:
        now = sum(row.clicks for row in data.search_daily)
        before = sum(row.clicks for row in data.search_daily_prev)
        metric = "clicurile din Google"
    else:
        return []
    change = _pct_change(now, before)
    if change is None or before < max(50, 100 * scale) or abs(change) < 20:
        return []
    falling = change < 0
    sign = "" if falling else "+"
    return [
        SeoInsight(
            id="overall_trend",
            rule="overall_trend",
            kind="alert" if falling else "info",
            priority="high" if falling else "low",
            title="Traficul site-ului scade" if falling else "Traficul site-ului crește",
            detail=(
                f"În ultimele {data.window.days} zile {metric} au fost {_int(now)}, față de "
                f"{_int(before)} în perioada anterioară ({sign}{_dec(change)}%)."
            ),
            action=(
                "Începe cu alertele de pe pagini și cuvinte de mai jos: acolo e, de obicei, "
                "cauza."
                if falling
                else "Vezi care pagini și cuvinte au adus creșterea și construiește în jurul lor."
            ),
            evidence={
                "Acum": _int(now),
                "Înainte": _int(before),
                "Evoluție": f"{sign}{_dec(change)}%",
            },
        )
    ]


_RULES = (
    _rule_overall_trend,
    _rule_page_traffic_drop,
    _rule_position_drop,
    _rule_question_gap,
    _rule_low_ctr,
    _rule_striking_distance,
    _rule_low_engagement,
    _rule_content_gap,
)
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_KIND_ORDER = {"alert": 0, "opportunity": 1, "info": 2}


def generate_insights(data: IntelligenceData) -> list[SeoInsight]:
    """Recomandarile perioadei, cele urgente primele.

    Pragurile sunt pentru 28 de zile si se scaleaza cu lungimea perioadei:
    100 de afisari in 7 zile nu inseamna acelasi lucru ca in 90.
    """
    scale = data.window.days / 28
    insights = [insight for rule in _RULES for insight in rule(data, scale)]
    # O intrebare cu recomandare de continut nu mai apare si ca "CTR mic" sau
    # "aproape de prima pagina" - acelasi cuvant, aceeasi pagina, o singura sarcina.
    questions = {item.subject for item in insights if item.rule == "question_gap"}
    insights = [
        item
        for item in insights
        if not (item.rule in {"low_ctr", "striking_distance"} and item.subject in questions)
    ]
    insights.sort(key=lambda item: (_PRIORITY_ORDER[item.priority], _KIND_ORDER[item.kind]))
    return insights[:_MAX_INSIGHTS]


def build_intelligence(
    sources: IntelligenceSources,
    *,
    domain: str,
    window: Window,
    generated_at: datetime | None = None,
) -> SEOIntelligencePayload:
    """Raportul complet: colectare, serie de timp, clasament, recomandari."""
    data, states, gaps = gather(sources, window)
    shown = {state.key: state.status for state in states}
    return SEOIntelligencePayload(
        domain=domain,
        period=ReportPeriod(start=window.start, end=window.end, days=window.days),
        previous_period=ReportPeriod(
            start=window.previous.start, end=window.previous.end, days=window.days
        ),
        generated_at=generated_at or datetime.now(tz=UTC),
        is_demo="demo" in shown.values(),
        sources=states,
        summary=build_summary(data),
        timeseries=build_timeseries(data),
        keywords=build_keywords(data),
        ai_recommendations=generate_insights(data),
        data_gaps=gaps,
    )
