"""Tehnicianul: tracking-ul si viteza pe mobil, verde/rosu, si veto-ul lui in consiliu.

Evaluatorul e pur: seriile zilnice si masuratoarea PageSpeed se dau direct.
Loader-ul (``DbTechnicalSignals``), jobul de noapte (``run_speed_check_job``) si
ruta se verifica pe SQLite, fara nicio cerere catre Google.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent_server.jobs.tasks import run_speed_check_job
from ppc_agent_server.models import (
    ConversionEvent,
    ConversionEventType,
    SearchTermConversion,
    SiteSpeedSample,
    TrackingEvidence,
)
from ppc_agent_server.services.humanizer import ai_tells
from ppc_agent_server.services.queen_signals import DbTechnicalSignals
from ppc_agent_server.services.technician import (
    DailyConversions,
    HealthStatus,
    MobileSpeed,
    SyntheticEvidence,
    TechnicalSignals,
    TechnicianDirective,
    TrackingStream,
    check_tracking,
    evaluate_technical_health,
    technician_facts,
)
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_agent import NOW
from tests_server.test_queen_council import _council, _CouncilVoice, _directive
from tests_server.test_queen_router import signed_in  # noqa: F401 - fixture

TODAY = NOW.date()


def _series(
    key: str, conversions: Sequence[float], clicks: Sequence[int] | None = None
) -> TrackingStream:
    """Un flux care se termina ieri: ultima valoare e ziua de ieri."""
    first = TODAY - timedelta(days=len(conversions))
    return TrackingStream(
        key=key,
        days=[
            DailyConversions(
                first + timedelta(days=offset), value, None if clicks is None else clicks[offset]
            )
            for offset, value in enumerate(conversions)
        ],
    )


def _speed(
    *,
    lcp: int | None = 1800,
    cls: float | None = 0.02,
    tbt: int | None = 120,
    score: int | None = 94,
    age_days: int = 1,
) -> MobileSpeed:
    return MobileSpeed(
        url="https://autofix.ro/",
        measured_at=NOW - timedelta(days=age_days),
        performance_score=score,
        lcp_ms=lcp,
        cls=cls,
        tbt_ms=tbt,
    )


def _signals(
    *streams: TrackingStream,
    speed: MobileSpeed | None = None,
    domain: str = "https://autofix.ro",
    previous: MobileSpeed | None = None,
    evidence: SyntheticEvidence | None = None,
) -> TechnicalSignals:
    return TechnicalSignals(
        domain=domain,
        today=TODAY,
        streams=streams,
        mobile_speed=speed,
        previous_mobile_speed=previous,
        evidence=evidence,
    )


def _evidence(
    *,
    status: int | None = 200,
    cta_ok: bool | None = True,
    ga4_ok: bool | None = True,
    meta_ok: bool | None = None,
    reason: str | None = None,
    days_ago: int = 1,
) -> SyntheticEvidence:
    return SyntheticEvidence(
        started_at=NOW - timedelta(days=days_ago),
        url="https://autofix.ro/contact",
        navigation_status=status,
        cta_selector="#contact-btn",
        cta_ok=cta_ok,
        ga4_ok=ga4_ok,
        meta_ok=meta_ok,
        failure_reason=reason,
        ga4_events=("page_view", "generate_lead"),
        meta_events=("PageView", "Lead") if meta_ok is not None else (),
    )


def _report(signals: TechnicalSignals) -> TechnicianDirective:
    return evaluate_technical_health(42, signals, generated_at=NOW)


#: 21 de zile cu 2 conversii din 30 de click-uri, apoi 4 zile cu click-uri si zero conversii.
BROKEN_TAG = _series("google_ads", [2.0] * 21 + [0.0] * 4, [30] * 25)
HEALTHY_TAG = _series("google_ads", [2.0] * 25, [30] * 25)
SLOW = _speed(lcp=4800, tbt=820, score=38)
#: Verificarea de dinainte, tot peste pragul critic de 4 s.
SLOW_BEFORE = _speed(lcp=4600, tbt=700, score=41, age_days=8)
#: Testul E2E: evenimentul GA4 n-a primit 2xx.
GA4_DOWN = _evidence(ga4_ok=False, reason="NETWORK_FAILURE")


# --- tracking-ul -------------------------------------------------------------------------


def test_conversions_that_stop_are_a_warning_not_a_veto() -> None:
    report = _report(_signals(BROKEN_TAG, speed=_speed()))

    [check] = report.tracking
    assert (check.status, check.finding, check.silent_days) == ("red", "conversions_stopped", 4)
    assert check.last_conversion == TODAY - timedelta(days=5)
    assert check.evidence == (
        "Nicio conversie în ultimele 4 zile (ultima pe 20 septembrie), deși reclamele au adus "
        "120 de click-uri. Înainte veneau 2 pe zi, deci lipsesc cel puțin 8 conversii."
    )
    assert check.fix is not None and "gtag" in check.fix and "GA4" in check.fix
    # O euristica nu e o dovada: fara test E2E picat, niciun veto - doar avertisment.
    assert (report.tracking_status, report.veto, report.veto_code) == ("red", "none", None)
    assert report.warnings[0].startswith("Conversiile Google Ads: Nicio conversie")
    assert "Fără veto: doar testul E2E dovedește" in report.warnings[0]
    assert report.recommendations[0] == check.fix


def test_when_the_clicks_stop_too_the_ads_stopped_not_the_tag() -> None:
    stream = _series("google_ads", [2.0] * 21 + [0.0] * 4, [30] * 21 + [3] * 4)

    check = check_tracking(stream, today=TODAY)

    assert (check.status, check.finding) == ("unknown", "traffic_stopped")
    assert "3 pe zi, față de 30 înainte" in check.evidence
    assert check.fix is None
    assert _report(_signals(stream)).veto == "none"


def test_a_quiet_spell_within_the_usual_pace_is_not_an_outage() -> None:
    # O conversie la doua zile: 4 zile fara nimic inseamna ~2 lipsa - sub pragul de 3.
    stream = _series("google_ads", [1.0, 0.0] * 10 + [0.0] * 3, [20] * 23)

    check = check_tracking(stream, today=TODAY)

    assert (check.status, check.silent_days) == ("green", 4)
    assert "intră în ritmul obișnuit de 0,5 pe zi" in check.evidence


def test_hundreds_of_clicks_and_never_a_conversion_mean_no_tag() -> None:
    never = check_tracking(_series("google_ads", [0.0] * 30, [12] * 30), today=TODAY)
    few_clicks = check_tracking(_series("google_ads", [0.0] * 30, [5] * 30), today=TODAY)

    assert (never.status, never.finding) == ("red", "never_converted")
    assert never.evidence.startswith("360 de click-uri în ultimele 30 de zile și nicio conversie")
    assert (few_clicks.status, few_clicks.finding) == ("unknown", "too_little_data")


def test_too_short_a_history_is_unknown_never_green() -> None:
    check = check_tracking(_series("gomag", [1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]), today=TODAY)

    assert (check.status, check.finding) == ("unknown", "too_little_data")
    assert "doar 2 conversii" in check.evidence


def test_webhook_orders_that_stop_are_judged_on_their_own_pace() -> None:
    check = check_tracking(_series("gomag", [3.0] * 20 + [0.0] * 3), today=TODAY)

    assert (check.status, check.finding) == ("red", "conversions_stopped")
    assert check.label == "comenzile trimise de magazinul GoMag"
    assert "lipsesc cel puțin 9 conversii" in check.evidence
    assert check.fix is not None
    assert check.fix.startswith("Verifică webhook-ul de comenzi din GoMag")


def test_today_is_never_judged() -> None:
    days = [
        DailyConversions(TODAY - timedelta(days=offset), 0.0 if offset == 0 else 2.0, 30)
        for offset in range(10)
    ]

    check = check_tracking(TrackingStream("google_ads", days), today=TODAY)

    assert (check.status, check.silent_days) == ("green", 0)
    assert check.last_conversion == TODAY - timedelta(days=1)


def test_without_any_conversion_source_it_asks_for_one() -> None:
    report = _report(_signals())

    assert (report.tracking_status, report.tracking) == ("unknown", [])
    assert any("Conectează o sursă de conversii" in rec for rec in report.recommendations)
    assert report.summary.startswith("Tracking: necunoscut. Nicio sursă de conversii conectată.")


# --- viteza pe mobil -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("speed", "status"),
    [
        (_speed(), "green"),
        (_speed(lcp=3200), "amber"),
        (_speed(lcp=4800, score=38), "red"),
        (_speed(cls=0.31), "red"),
        (_speed(tbt=820), "red"),
        (_speed(lcp=None, cls=None, tbt=None, score=42), "red"),
        (_speed(lcp=None, cls=None, tbt=None, score=None), "unknown"),
    ],
)
def test_mobile_speed_is_judged_on_google_thresholds(
    speed: MobileSpeed, status: HealthStatus
) -> None:
    assert _report(_signals(HEALTHY_TAG, speed=speed)).speed_status == status


def test_one_slow_check_is_only_a_warning() -> None:
    report = _report(_signals(HEALTHY_TAG, speed=SLOW))

    assert (report.speed_status, report.veto, report.veto_code) == ("red", "none", None)
    assert any("fără veto: veto-ul cere LCP peste 4 s la două" in w for w in report.warnings)


def test_two_consecutive_critical_lcp_checks_veto_extra_spend() -> None:
    report = _report(_signals(HEALTHY_TAG, speed=SLOW, previous=SLOW_BEFORE))

    assert (report.speed_status, report.veto, report.veto_code) == (
        "red",
        "spend",
        "MOBILE_LCP_CRITICAL",
    )
    assert report.veto_reason == (
        "Site-ul e lent pe mobil la două verificări la rând (LCP 4,6 s, apoi 4,8 s; pragul "
        "critic e 4 s): trafic plătit în plus ar plăti click-uri care pleacă înainte să vadă "
        "oferta."
    )
    assert report.mobile_speed.evidence == (
        "Pe mobil, pagina e lentă: LCP 4,8 s (bun până la 2,5 s, slab peste 4 s), TBT 820 ms "
        "(bun până la 200 ms, slab peste 600 ms). Scor PageSpeed: 38 din 100."
    )
    assert [fix.split(":")[0] for fix in report.recommendations] == ["LCP", "TBT"]


def test_a_borderline_page_is_amber_without_a_veto() -> None:
    report = _report(_signals(HEALTHY_TAG, speed=_speed(lcp=3200, score=81)))

    assert (report.speed_status, report.veto, report.status) == ("amber", "none", "amber")
    assert report.mobile_speed.evidence.startswith("Pe mobil, pagina e la limită: LCP 3,2 s")
    assert report.recommendations[0].startswith("LCP:")


def test_speed_without_a_fresh_measurement_is_unknown_and_says_why() -> None:
    no_domain = _report(_signals(HEALTHY_TAG, domain=""))
    pending = _report(_signals(HEALTHY_TAG))
    stale = _report(_signals(HEALTHY_TAG, speed=_speed(lcp=6000, age_days=30)))

    assert "domeniul site-ului lipsește" in no_domain.mobile_speed.evidence
    assert any("Setări" in rec for rec in no_domain.recommendations)
    assert "rulează noaptea" in pending.mobile_speed.evidence
    assert pending.recommendations == []
    assert "prea veche" in stale.mobile_speed.evidence
    assert (stale.speed_status, stale.veto) == ("unknown", "none")
    # Tracking verde + viteza nemasurata nu e "verde" de ansamblu.
    assert pending.status == "unknown"


def test_a_critical_lcp_below_the_threshold_once_does_not_veto() -> None:
    fast_before = _speed(lcp=3900, age_days=8)

    report = _report(_signals(HEALTHY_TAG, speed=SLOW, previous=fast_before))

    assert report.veto_code is None


@pytest.mark.parametrize(
    ("evidence", "code"),
    [
        (_evidence(status=503, reason="SITE_UNAVAILABLE"), "SITE_UNAVAILABLE"),
        (_evidence(status=None, reason="SITE_UNAVAILABLE"), "SITE_UNAVAILABLE"),
        (_evidence(cta_ok=False, reason="CRITICAL_JOURNEY_BROKEN"), "CRITICAL_JOURNEY_BROKEN"),
        (GA4_DOWN, "ATTRIBUTION_BROKEN"),
        (_evidence(meta_ok=False, reason="DATALAYER_MISSING"), "ATTRIBUTION_BROKEN"),
    ],
)
def test_only_proven_failures_veto_money_decisions(
    evidence: SyntheticEvidence, code: str
) -> None:
    report = _report(_signals(HEALTHY_TAG, speed=_speed(), evidence=evidence))

    assert (report.veto, report.veto_code) == ("money", code)
    assert report.tracking_status == "red"


def test_a_passed_or_consent_blocked_or_stale_test_does_not_veto() -> None:
    passed = _report(_signals(BROKEN_TAG, evidence=_evidence()))
    blocked = _evidence(ga4_ok=None, reason="CONSENT_BLOCKED")
    consent = _report(_signals(HEALTHY_TAG, evidence=blocked))
    stale = _report(_signals(HEALTHY_TAG, evidence=_evidence(ga4_ok=False, days_ago=10)))

    # Dovada E2E bate euristica: tracking-ul e verde, desi seriile arata o tacere.
    assert (passed.veto, passed.tracking_status) == ("none", "green")
    assert passed.synthetic == (
        "Test E2E (24 septembrie): trecut. Evenimentele din contract au ajuns cu 2xx."
    )
    assert (consent.veto, consent.tracking_status) == ("none", "unknown")
    assert any("Consimțământul a blocat testul E2E" in w for w in consent.warnings)
    assert (stale.veto, stale.synthetic) == ("none", None)
    assert any("mai vechi de 3 zile" in w for w in stale.warnings)


def test_a_broken_journey_outranks_a_slow_site() -> None:
    evidence = _evidence(cta_ok=False, reason="CRITICAL_JOURNEY_BROKEN")

    report = _report(_signals(HEALTHY_TAG, speed=SLOW, previous=SLOW_BEFORE, evidence=evidence))

    assert report.veto_code == "CRITICAL_JOURNEY_BROKEN"
    assert report.veto_reason == (
        "Drumul spre conversie e rupt: butonul «#contact-btn» lipsește sau nu se poate apăsa "
        "pe https://autofix.ro/contact (test sintetic, 24 septembrie)."
    )
    assert report.recommendations[0].startswith("Verifică butonul «#contact-btn»")
    assert [fix.split(":")[0] for fix in report.recommendations[1:]] == ["LCP", "TBT"]


# --- vocea -------------------------------------------------------------------------------


def test_the_position_is_a_short_engineering_diagnosis() -> None:
    summary = _report(_signals(BROKEN_TAG, speed=SLOW, evidence=GA4_DOWN)).summary

    assert summary.startswith(
        "Tracking: roșu. Test E2E (24 septembrie): NETWORK_FAILURE pe https://autofix.ro/contact."
    )
    assert "Mobil: roșu. Pe mobil, pagina e lentă" in summary
    assert "Veto pe orice decizie de buget până se repară tracking-ul." in summary
    assert "Întâi: verifică tag-urile GA4 pe https://autofix.ro/contact" in summary


def test_no_deterministic_technician_text_sounds_generated() -> None:
    texts: list[str] = []
    for signals in (
        _signals(BROKEN_TAG, speed=SLOW),
        _signals(BROKEN_TAG, speed=SLOW, previous=SLOW_BEFORE, evidence=GA4_DOWN),
        _signals(HEALTHY_TAG, evidence=_evidence(status=503, reason="SITE_UNAVAILABLE")),
        _signals(HEALTHY_TAG, evidence=_evidence(cta_ok=False)),
        _signals(HEALTHY_TAG, speed=_speed(lcp=3200, cls=0.2)),
        _signals(_series("gomag", [3.0] * 20 + [0.0] * 3), domain=""),
        _signals(),
    ):
        report = _report(signals)
        texts.extend([report.summary, technician_facts(report), report.veto_reason or ""])
    assert [(text[:60], ai_tells(text)) for text in texts if ai_tells(text)] == []


# --- veto-ul in consiliu -------------------------------------------------------------------


def test_broken_tracking_vetoes_every_money_decision_in_the_council() -> None:
    technical = _signals(BROKEN_TAG, speed=_speed(), evidence=GA4_DOWN)
    reply = _council(technical=technical).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    ruling = reply.ruling
    assert reply.technical is not None
    assert ruling.decision.startswith("Nu acum. Tracking-ul e picat pe GA4")
    assert ruling.veto == reply.technical.veto_reason
    assert any(idea.startswith("creșterea treptată") for idea in ruling.vetoed)
    assert not any(idea.startswith("creșterea") for idea in ruling.approved)
    # Textele noi ale Reginei se opresc si ele: un test A/B fara conversii n-are castigator.
    assert any(idea.startswith("rescrierea reclamei") for idea in ruling.vetoed)
    assert not any(idea.startswith("rescrierea") for idea in ruling.approved)
    assert "Propun rescrierea" not in reply.reply
    assert "atunci oprim reclamele până se repară" in ruling.decision
    assert "Reparația de făcut întâi: verifică tag-urile GA4" in reply.reply
    assert [opinion.member for opinion in reply.opinions] == [
        "strategist", "cfo", "technician", "cpo"
    ]
    assert reply.opinions[2].opinion == reply.technical.summary


def test_a_broken_site_pauses_the_ads_outright() -> None:
    technical = _signals(HEALTHY_TAG, evidence=_evidence(status=503, reason="SITE_UNAVAILABLE"))
    reply = _council(technical=technical).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    assert reply.ruling.decision.startswith("Nu acum. Site-ul nu e disponibil")
    assert "Oprim reclamele până se repară" in reply.ruling.decision
    assert "Dacă s-au oprit și comenzile reale" not in reply.ruling.decision


def test_a_slow_mobile_site_blocks_extra_spend_but_not_rewrites() -> None:
    technical = _signals(HEALTHY_TAG, speed=SLOW, previous=SLOW_BEFORE)
    reply = _council(technical=technical).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    ruling = reply.ruling
    assert ruling.decision.startswith("Nu acum. Site-ul e lent pe mobil la două verificări")
    assert ruling.decision.endswith("Întâi viteza pe mobil, apoi bugetul.")
    # Reparatia incepe cu un acronim: ramane "LCP", nu devine "lCP".
    assert "Reparația de făcut întâi: LCP: comprimă imaginea principală" in reply.reply
    assert any(idea.startswith("creșterea treptată") for idea in ruling.vetoed)
    assert any(idea.startswith("rescrierea reclamei") for idea in ruling.approved)


def test_new_ad_copy_waits_for_the_tracking_fix() -> None:
    reply = _council(technical=_signals(HEALTHY_TAG, evidence=GA4_DOWN)).evaluate_client_query(
        "Ce texte noi să pun în reclame?", _directive()
    )

    assert reply.ruling.decision.startswith("Nu acum. Tracking-ul e picat")
    assert "fără conversii măsurate, nu are câștigător" in reply.ruling.decision


def test_the_veto_is_told_even_when_the_question_is_about_the_audience() -> None:
    reply = _council(technical=_signals(HEALTHY_TAG, evidence=GA4_DOWN)).evaluate_client_query(
        "Cine e clientul meu ideal?", _directive()
    )

    assert reply.ruling.decision.startswith("Publicul pe care merită să construiești")
    assert "Tehnicianul a pus veto: tracking-ul e picat pe GA4" in reply.reply


def test_without_a_veto_the_council_rules_as_before() -> None:
    with_technician = _council(technical=_signals(HEALTHY_TAG, speed=_speed()))
    without = _council()
    question = "Merită să cresc bugetul?"

    ruled = with_technician.evaluate_client_query(question, _directive()).ruling
    before = without.evaluate_client_query(question, _directive()).ruling

    assert (ruled.veto, ruled.vetoed) == (None, [])
    assert (ruled.decision, ruled.approved, ruled.cut) == (
        before.decision,
        before.approved,
        before.cut,
    )


def test_the_technician_position_and_the_veto_reach_the_synthesis() -> None:
    voice = _CouncilVoice()
    technical = _signals(BROKEN_TAG, evidence=GA4_DOWN)
    reply = _council(voice=voice, technical=technical).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    assert voice.roles == ["chair"]
    # Veto-ul opreste cresterea de buget sustinuta de CFO: CFO-ul ii raspunde Tehnicianului.
    [rebuttal] = reply.rebuttals
    assert (rebuttal.member, rebuttal.replying_to, rebuttal.conflict) == (
        "cfo", "technician", "veto"
    )
    assert rebuttal.reopen_when.startswith("testul E2E confirmă")
    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "technician"]
    assert reply.technical is not None
    assert (opinion.source, opinion.opinion, opinion.title) == (
        "template",
        reply.technical.summary,
        "Tehnicianul · tracking și viteză",
    )
    chair = voice.prompt("chair")
    for part in (
        f"- Tehnicianul (tracking și viteză): {opinion.opinion}",
        "Veto-ul Tehnicianului (obligatoriu): Tracking-ul e picat",
        "Oprit de veto-ul Tehnicianului: creșterea treptată",
        "RUNDA DE REPLICI:\n- CFO-ul (rentabilitate), către Tehnicianul (tracking și viteză):",
        "Se rediscută când testul E2E confirmă că tracking-ul trimite din nou conversiile.",
    ):
        assert part in chair
    assert "FAPTE TEHNICE" not in chair


def test_without_technical_data_the_technician_is_not_asked() -> None:
    voice = _CouncilVoice()
    reply = _council(voice=voice, technical=_signals(domain="")).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    assert voice.roles == ["chair"]
    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "technician"]
    assert opinion.source == "template"
    assert opinion.fallback_reason is not None and "Fără date" in opinion.fallback_reason
    assert reply.ruling.veto is None


# --- datele din baza de date --------------------------------------------------------------


def _at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def _event(account_id: int, source: str, when: datetime) -> ConversionEvent:
    return ConversionEvent(
        client_account_id=account_id,
        event_id=f"{source}-{when.isoformat()}-{id(when)}",
        event_type=ConversionEventType.PURCHASE,
        source_platform=source,
        qualified=True,
        created_at=when,
    )


def _speed_row(account_id: int, when: datetime, lcp: int) -> SiteSpeedSample:
    return SiteSpeedSample(
        client_account_id=account_id,
        url="https://autofix.ro/",
        performance_score=40,
        lcp_ms=lcp,
        layout_shift=0.05,
        tbt_ms=300,
        measured_at=when,
    )


def test_database_signals_are_daily_series_with_the_silent_days_included(
    session: Session,
) -> None:
    account = _client_account(session)
    account_id = account.id or 0
    account.google_ads_customer_id = "123-456-7890"
    account.meta_ad_account_id = "act_1"
    account.target_domain = "https://autofix.ro"
    session.add(account)
    for day_offset, clicks, conversions in ((3, 20, 1.0), (3, 30, 2.0), (10, 25, 1.5), (40, 99, 9)):
        session.add(
            SearchTermConversion(
                client_account_id=account_id,
                day=_at(TODAY - timedelta(days=day_offset)),
                search_term=f"termen {clicks}",
                clicks=clicks,
                cost=Decimal("10"),
                conversions=conversions,
            )
        )
    for when in (
        _at(TODAY - timedelta(days=2), 9),
        _at(TODAY - timedelta(days=2), 15),
        _at(TODAY - timedelta(days=45)),
    ):
        session.add(_event(account_id, "gomag", when))
    session.add(_event(account_id, "call_tracker", _at(TODAY - timedelta(days=50))))
    session.add(_speed_row(account_id, _at(TODAY - timedelta(days=9)), 5200))
    session.add(_speed_row(account_id, _at(TODAY - timedelta(days=1)), 2100))
    session.commit()

    signals = DbTechnicalSignals(session, today=lambda: TODAY).load(account_id)

    assert [stream.key for stream in signals.streams] == ["google_ads", "call_tracker", "gomag"]
    google, calls, orders = signals.streams
    assert len(google.days) == 30
    assert (google.days[0].day, google.days[-1].day) == (
        TODAY - timedelta(days=30),
        TODAY - timedelta(days=1),
    )
    by_day = {day.day: day for day in google.days}
    assert by_day[TODAY - timedelta(days=3)] == DailyConversions(TODAY - timedelta(days=3), 3.0, 50)
    assert by_day[TODAY - timedelta(days=4)] == DailyConversions(TODAY - timedelta(days=4), 0.0, 0)
    assert sum(day.conversions for day in google.days) == 4.5  # randul de acum 40 de zile, afara
    # O sursa tacuta de peste o luna ramane in raport - exact ce trebuie vazut.
    assert sum(day.conversions for day in calls.days) == 0
    assert orders.days[-2].conversions == 2.0
    assert all(day.clicks is None for day in orders.days)
    assert signals.mobile_speed is not None and signals.mobile_speed.lcp_ms == 2100
    assert signals.domain == "https://autofix.ro"
    assert any(note.startswith("Pixelul Meta") for note in signals.notes)


def test_a_client_without_google_ads_or_webhooks_has_no_streams(session: Session) -> None:
    account = _client_account(session)

    signals = DbTechnicalSignals(session, today=lambda: TODAY).load(account.id or 0)

    assert (signals.streams, signals.mobile_speed, signals.domain) == ([], None, "")
    with pytest.raises(LookupError):
        DbTechnicalSignals(session).load(999_999)


# --- masuratoarea de noapte ------------------------------------------------------------------


@pytest.mark.parametrize("domain", ["https://autofix.ro", "autofix.ro", "https://autofix.ro/"])
def test_the_nightly_speed_check_stores_a_mobile_sample(session: Session, domain: str) -> None:
    account = _client_account(session)
    account.target_domain = domain
    session.add(account)
    session.commit()
    seen: list[str] = []

    def measure(url: str) -> dict[str, Any] | None:
        seen.append(url)
        return {
            "performance_score": 38,
            "largest_contentful_paint": "4,8 s",
            "lcp_ms": 4830.0,
            "cls": 0.312,
            "tbt_ms": 820.0,
        }

    result = run_speed_check_job(client_account_id=account.id or 0, measure=measure)

    assert seen == ["https://autofix.ro/"]
    assert result == {
        "measured": True,
        "url": "https://autofix.ro/",
        "performance_score": 38,
        "lcp_ms": 4830,
    }
    [sample] = session.exec(select(SiteSpeedSample)).all()
    assert (
        sample.strategy,
        sample.performance_score,
        sample.lcp_ms,
        sample.layout_shift,
        sample.tbt_ms,
    ) == (
        "mobile",
        38,
        4830,
        0.312,
        820,
    )


def test_nothing_is_stored_without_a_domain_or_when_pagespeed_fails(session: Session) -> None:
    account = _client_account(session)

    def unreachable(url: str) -> dict[str, Any] | None:
        raise AssertionError("fara domeniu nu se masoara nimic")

    without_domain = run_speed_check_job(client_account_id=account.id or 0, measure=unreachable)
    account.target_domain = "https://autofix.ro"
    session.add(account)
    session.commit()
    failed = run_speed_check_job(client_account_id=account.id or 0, measure=lambda url: None)

    assert without_domain == {"measured": False, "reason": "fara domeniu in Setari"}
    assert failed["measured"] is False
    assert session.exec(select(SiteSpeedSample)).all() == []


# --- rutele ------------------------------------------------------------------------------

Signed = tuple[TestClient, FastAPI, dict[str, str], int]


def _seed_stopped_conversions(session: Session, account_id: int) -> None:
    """Conversii zilnice din Google Ads, apoi 5 zile cu click-uri si nicio conversie."""
    today = datetime.now(tz=UTC).date()
    for day_offset in range(1, 26):
        session.add(
            SearchTermConversion(
                client_account_id=account_id,
                day=_at(today - timedelta(days=day_offset)),
                search_term="service cutie automata pret",
                clicks=30,
                cost=Decimal("40"),
                conversions=0.0 if day_offset <= 5 else 2.0,
            )
        )
    session.commit()


def _seed_failed_e2e(session: Session, account_id: int) -> None:
    """Testul sintetic de azi-noapte: generate_lead n-a primit 2xx de la GA4."""
    session.add(
        TrackingEvidence(
            client_account_id=account_id,
            url="https://autofix.ro/contact",
            started_at=datetime.now(tz=UTC) - timedelta(hours=6),
            navigation_status=200,
            cta_selector="#contact-btn",
            cta_ok=True,
            ga4_transport_ok=False,
            failure_reason="NETWORK_FAILURE",
            evidence={"verdict": {"ga4": {"expected_events": ["page_view", "generate_lead"]}}},
        )
    )
    session.commit()


@pytest.fixture
def broken(signed_in: Signed, session: Session) -> Iterator[Signed]:  # noqa: F811
    _seed_stopped_conversions(session, signed_in[3])
    _seed_failed_e2e(session, signed_in[3])
    yield signed_in


def test_the_technician_report_route(broken: Signed) -> None:
    client, _, headers, account_id = broken

    response = client.get("/api/v1/queen/technician", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_account_id"] == account_id
    assert (body["tracking_status"], body["speed_status"], body["veto"]) == (
        "red",
        "unknown",
        "money",
    )
    assert body["tracking"][0]["finding"] == "conversions_stopped"
    assert body["veto_code"] == "ATTRIBUTION_BROKEN"
    assert body["summary"].startswith("Tracking: roșu. Test E2E")
    assert client.get("/api/v1/queen/technician").status_code == 401


def test_the_chat_carries_the_technician_veto(broken: Signed) -> None:
    client, _, headers, _ = broken

    response = client.post(
        "/api/v1/queen/chat", headers=headers, json={"message": "Merită să cresc bugetul?"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["technical"]["veto"] == "money"
    assert body["ruling"]["veto"].startswith("Tracking-ul e picat pe GA4")
    assert body["reply"].startswith("Nu acum. Tracking-ul e picat")
    assert [opinion["member"] for opinion in body["opinions"]] == [
        "strategist",
        "cfo",
        "technician",
        "researcher",
        "cpo",
    ]
