"""Datele agentului SEO/GEO in faptele consiliului.

- Regina (CMO): traficul din GA4 pe canale (Meta fata de Google organic), Search
  Console si pozitiile urmarite - corelate determinist (``organic_context.py``).
- Tehnicianul (CTO): ultimul audit tehnic SEO/GEO (``SiteAuditSnapshot``, scris noaptea
  de ``run_site_audit_job``) si datele CrUX din PageSpeed.
- Consiliul in flux: evenimentele deliberarii (``CouncilEvent``), fara ca vreun
  ascultator sa poata strica raspunsul.

Fara retea: GA4 si Search Console sunt surse false, auditul primeste un raport gata
facut, PageSpeed nu ruleaza.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlmodel import Session, select

from ppc_agent.search_data.analytics import AnalyticsDataClient
from ppc_agent.search_data.google_oauth import OAUTH_TOKEN_URL
from ppc_agent_server import seo_intelligence
from ppc_agent_server.jobs import tasks
from ppc_agent_server.jobs.tasks import audit_snapshot, run_site_audit_job
from ppc_agent_server.jobs.tasks import run_site_audit as real_run_site_audit
from ppc_agent_server.models import (
    ClientAccount,
    SerpPosition,
    SerpSource,
    SiteAuditSnapshot,
    SiteSpeedSample,
)
from ppc_agent_server.services.council import (
    CHAIR_SYSTEM_PROMPT,
    CouncilEvent,
    strategist_position,
)
from ppc_agent_server.services.organic_context import (
    ChannelSessions,
    KeywordRank,
    OrganicSearchTotals,
    OrganicSignals,
    build_organic_context,
    organic_facts,
)
from ppc_agent_server.services.queen_agent import (
    StreamingTextGenerator,
    build_directive,
    cmo_facts,
)
from ppc_agent_server.services.queen_signals import (
    DbBrandSignals,
    DbTechnicalSignals,
    GoogleOrganicTraffic,
    load_keyword_ranks,
)
from ppc_agent_server.services.technician import (
    AuditIssue,
    SiteAudit,
    check_site_audit,
    evaluate_technical_health,
    technician_facts,
)
from seo_geo_agent.audit.issues import AUDIT_ISSUE_TYPES
from seo_geo_agent.audit.page_reporters import DetectedIssue
from seo_geo_agent.audit.scoring import PillarScore
from seo_geo_agent.audit.service import AuditResult
from seo_geo_agent.audit.types import CrawledPage
from seo_geo_agent.services.intelligence import DailySearch, IntelligenceSources, Window
from tests_server.test_brand_alignment import _FakeSeoIntent
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_agent import NOW, _signals
from tests_server.test_queen_council import (
    CHAIR_SAYS,
    LOSING,
    _council,
    _CouncilVoice,
    _directive,
)
from tests_server.test_technician import _signals as _technical_signals
from tests_server.test_technician import _speed

TODAY = NOW.date()

# --- Regina: Meta fata de Google organic ------------------------------------------------


def _channels(paid: tuple[int, int], organic: tuple[int, int]) -> list[ChannelSessions]:
    return [
        ChannelSessions("Paid Social", paid[0], paid[1]),
        ChannelSessions("Organic Search", organic[0], organic[1]),
        ChannelSessions("Direct", 300, 310),
    ]


@pytest.mark.parametrize(
    ("paid", "organic", "shift"),
    [
        ((600, 800), (1300, 1100), "organic_offsets_paid"),
        ((600, 800), (900, 1100), "both_declining"),
        ((600, 800), (1110, 1100), "paid_decline_only"),
        ((800, 800), (1300, 1100), "organic_growth"),
        ((800, 790), (1100, 1100), "stable"),
        ((10, 20), (1300, 1100), "unknown"),  # prea putine sesiuni pe Meta ca sa insemne ceva
    ],
)
def test_meta_and_organic_traffic_are_correlated_deterministically(
    paid: tuple[int, int], organic: tuple[int, int], shift: str
) -> None:
    context = build_organic_context(OrganicSignals(28, channels=_channels(paid, organic)))

    assert context.shift == shift


def test_the_queen_sees_the_numbers_behind_the_correlation() -> None:
    signals = OrganicSignals(
        28,
        channels=_channels((600, 800), (1300, 1100)),
        search=OrganicSearchTotals(420, 350, 18500, 16000, 6.9, 8.4),
        keywords=[
            KeywordRank("service auto sector 3", 9.0, 4.0),
            KeywordRank("schimb ulei cutie automata", 3.0, 3.0),  # nu s-a miscat
            KeywordRank("itp bucuresti", None, 7.0),
        ],
    )

    context = build_organic_context(signals)

    assert (context.paid_social_change, context.organic_search_change) == (-0.25, 0.1818)
    assert context.evidence == [
        "GA4, ultimele 28 de zile față de cele 28 dinainte: Paid Social (Meta) 600 de sesiuni "
        "(-25%); Organic Search (Google) 1300 de sesiuni (+18%).",
        "Google organic (Search Console): 420 de click-uri (+20%), 18500 de afișări, poziție "
        "medie 6,9 (înainte 8,4).",
        "Poziții urmărite în Google: «itp bucuresti»: în afara rezultatelor -> locul 7; "
        "«service auto sector 3»: locul 9 -> locul 4.",
    ]
    assert context.implication.startswith("Meta aduce mai puțin trafic, dar Google organic")
    facts = organic_facts(context)
    assert facts[-1].startswith("Meta față de organic (obligatoriu): Meta aduce mai puțin")
    assert all(line.startswith("Trafic (calculat determinist): ") for line in facts[:-1])


def test_without_ga4_the_queen_is_told_what_is_missing() -> None:
    note = "GA4 nu e conectat: nu pot compara traficul din Meta cu cel din Google organic."

    context = build_organic_context(OrganicSignals(28, notes=[note]))

    assert (context.shift, context.evidence, context.implication) == ("unknown", [], "")
    assert organic_facts(context) == [note]


def test_the_organic_context_reaches_the_cmo_facts() -> None:
    organic = OrganicSignals(28, channels=_channels((600, 800), (1300, 1100)))

    directive = build_directive(42, _signals(organic=organic), generated_at=NOW)

    assert directive.organic_context is not None
    assert directive.organic_context.shift == "organic_offsets_paid"
    facts = cmo_facts(directive)
    assert "Paid Social (Meta) 600 de sesiuni (-25%)" in facts
    assert "Meta față de organic (obligatoriu): Meta aduce mai puțin trafic" in facts
    # Fara trafic citit, faptele raman cele de dinainte.
    assert build_directive(42, _signals(), generated_at=NOW).organic_context is None


def test_the_brand_position_carries_the_meta_organic_correlation() -> None:
    organic = OrganicSignals(28, channels=_channels((600, 800), (1300, 1100)))
    directive = build_directive(42, _signals(organic=organic), generated_at=NOW)
    voice = _CouncilVoice()

    reply = _council(voice=voice).evaluate_client_query("De ce scade traficul din Meta?", directive)

    # Strategul nu mai scrie cu LLM-ul: corelarea intra direct in pozitia lui, din date.
    assert directive.organic_context is not None
    implication = directive.organic_context.implication
    assert implication in strategist_position(directive)
    assert implication in reply.opinions[0].opinion
    chair = voice.prompt("chair")
    assert implication in chair  # din pozitia Strategului, nu din cifrele GA4 brute
    assert "Paid Social (Meta) 600 de sesiuni" not in chair
    assert "ca o corelare, nu ca o cauză" in CHAIR_SYSTEM_PROMPT
    assert implication not in strategist_position(build_directive(42, _signals(), generated_at=NOW))


class _FakeGa4Client:
    """``AnalyticsDataClient`` fals: sesiunile pe canal, dupa perioada ceruta."""

    def __init__(self, today: date) -> None:
        self.windows: list[tuple[date, date]] = []
        self._today = today

    def channel_sessions(self, *, start_date: date, end_date: date) -> dict[str, int]:
        self.windows.append((start_date, end_date))
        recent = end_date > self._today - timedelta(days=20)
        return (
            {"Paid Social": 600, "Organic Search": 1300}
            if recent
            else {"Paid Social": 800, "Organic Search": 1100, "Referral": 40}
        )


class _FakeGsc:
    def __init__(self, today: date) -> None:
        self._today = today

    def daily(self, window: Window) -> list[DailySearch]:
        recent = window.end > self._today - timedelta(days=20)
        clicks, position = (15, 6.9) if recent else (12, 8.4)
        return [DailySearch(day, clicks, 600, position) for day in window.dates()]

    def queries(self, window: Window) -> list[Any]:
        return []


def test_live_ga4_and_search_console_become_organic_signals(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _client_account(session)
    ga4 = _FakeGa4Client(TODAY)

    def sources(account: ClientAccount, **kwargs: Any) -> IntelligenceSources:
        return IntelligenceSources(
            analytics=seo_intelligence.Ga4AnalyticsSource(ga4),  # type: ignore[arg-type]
            analytics_status="live",
            search=_FakeGsc(TODAY),
            search_status="live",
            volumes=None,
            volumes_status="not_connected",
            notes={},
        )

    monkeypatch.setattr(seo_intelligence, "build_sources", sources)

    signals = GoogleOrganicTraffic(today=lambda: TODAY).load(account)

    assert signals.notes == []
    by_channel = {channel.channel: channel for channel in signals.channels}
    assert by_channel["Paid Social"] == ChannelSessions("Paid Social", 600, 800)
    assert by_channel["Referral"] == ChannelSessions("Referral", 0, 40)
    # Doua perioade egale, alaturate, care se termina cu intarzierea datelor Google.
    (now_start, now_end), (before_start, before_end) = ga4.windows
    assert (now_end - now_start, before_end - before_start) == (timedelta(days=27),) * 2
    assert before_end == now_start - timedelta(days=1)
    assert signals.search == OrganicSearchTotals(420, 336, 16800, 16800, 6.9, 8.4)


def test_an_unconnected_account_gets_notes_not_demo_traffic(session: Session) -> None:
    account = _client_account(session)

    signals = GoogleOrganicTraffic(today=lambda: TODAY).load(account)

    assert (list(signals.channels), signals.search) == ([], None)
    assert signals.notes == [
        "GA4 nu e conectat: nu pot compara traficul din Meta cu cel din Google organic."
    ]


def _position(
    account_id: int, keyword: str, days_ago: int, rank: float | None, domain: str = "autofix.ro"
) -> SerpPosition:
    return SerpPosition(
        client_account_id=account_id,
        checked_on=datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()),
        keyword=keyword,
        domain=domain,
        source=SerpSource.OPENSERP,
        rank=rank,
    )


def test_tracked_positions_compare_the_last_check_of_each_period(session: Session) -> None:
    account = _client_account(session)
    account.target_domain = "https://www.autofix.ro/"
    session.add(account)
    account_id = account.id or 0
    session.add_all(
        [
            _position(account_id, "service auto sector 3", 50, 12.0),
            _position(account_id, "service auto sector 3", 35, 9.0),
            _position(account_id, "service auto sector 3", 3, 4.0),
            _position(account_id, "itp bucuresti", 40, None),
            _position(account_id, "itp bucuresti", 2, 7.0),
            _position(account_id, "doar recent", 2, 5.0),  # fara perioada de comparat
            _position(account_id, "service auto sector 3", 2, 1.0, domain="concurent.ro"),
        ]
    )
    session.commit()

    ranks = load_keyword_ranks(session, account, today=TODAY)

    assert ranks == [
        KeywordRank("itp bucuresti", None, 7.0),
        KeywordRank("service auto sector 3", 9.0, 4.0),
    ]


class _Traffic:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def load(self, account: ClientAccount) -> OrganicSignals:
        if self.error is not None:
            raise self.error
        return OrganicSignals(28, channels=_channels((600, 800), (1300, 1100)))


def test_the_brand_loader_adds_the_traffic_and_never_fails_on_it(session: Session) -> None:
    account = _client_account(session)

    ok = DbBrandSignals(
        session, seo_intent=_FakeSeoIntent(), traffic=_Traffic(), today=lambda: TODAY
    ).load(account.id or 0)
    down = DbBrandSignals(
        session,
        seo_intent=_FakeSeoIntent(),
        traffic=_Traffic(RuntimeError("token expirat")),
        today=lambda: TODAY,
    ).load(account.id or 0)

    assert ok.organic is not None and len(ok.organic.channels) == 3
    assert down.organic is not None and list(down.organic.channels) == []
    assert down.organic.notes == ["Traficul din Google nu s-a putut citi (RuntimeError)."]


def test_ga4_channel_sessions_come_from_the_default_channel_group() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "access-ga4"})
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "dimensionHeaders": [{"name": "sessionDefaultChannelGroup"}],
                "metricHeaders": [{"name": "sessions", "type": "TYPE_INTEGER"}],
                "rows": [
                    {"dimensionValues": [{"value": value}], "metricValues": [{"value": count}]}
                    for value, count in (("Paid Social", "600"), ("Organic Search", "1300"))
                ],
            },
        )

    client = AnalyticsDataClient(
        property_id="properties/123",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),
    )

    sessions = client.channel_sessions(start_date=date(2026, 9, 1), end_date=date(2026, 9, 28))

    assert sessions == {"Paid Social": 600, "Organic Search": 1300}
    [body] = bodies
    assert body["dimensions"] == [{"name": "sessionDefaultChannelGroup"}]
    assert body["metrics"] == [{"name": "sessions"}]


# --- Tehnicianul: auditul SEO/GEO si CrUX ------------------------------------------------

AUDIT = SiteAudit(
    audited_at=NOW - timedelta(days=1),
    url="https://autofix.ro/",
    pages_crawled=18,
    completed=True,
    seo_score=72,
    geo_score=55,
    critical=2,
    warnings=5,
    issues=[
        AuditIssue("Pagini fără titlu", "critical", 3, "Scrie un titlu unic pe fiecare pagină"),
        AuditIssue("Imagini fără text alternativ", "warning", 9, "Adaugă atributul alt"),
    ],
)


def test_the_audit_summary_carries_scores_counts_and_fixes() -> None:
    check = check_site_audit(AUDIT, today=TODAY)

    assert check is not None and check.fresh
    assert check.evidence == (
        "Auditul tehnic din 24 septembrie pe 18 pagini: scor SEO 72 din 100, GEO 55 din 100; "
        "2 probleme critice, 5 avertismente."
    )
    assert check.issues == [
        "Pagini fără titlu (critică, 3 pagini): Scrie un titlu unic pe fiecare pagină",
        "Imagini fără text alternativ (avertisment, 9 pagini): Adaugă atributul alt",
    ]
    assert check_site_audit(None, today=TODAY) is None


def test_an_old_or_partial_audit_says_so() -> None:
    old = replace(
        AUDIT,
        audited_at=NOW - timedelta(days=20),
        pages_crawled=25,
        completed=False,
        seo_score=None,
        geo_score=None,
        critical=0,
        warnings=1,
        issues=(),
    )

    check = check_site_audit(old, today=TODAY)

    assert check is not None and not check.fresh
    assert "(parțial: crawl-ul s-a oprit din buget)" in check.evidence
    assert "scor" not in check.evidence
    assert check.evidence.endswith(
        "E mai vechi de 14 zile: poate să nu mai descrie site-ul de azi."
    )


def test_the_cto_facts_include_the_audit_and_the_real_users() -> None:
    crux = replace(_speed(lcp=3100), field_lcp_ms=2900, field_cls=0.04, field_inp_ms=240)
    signals = _technical_signals(speed=crux)
    with_audit = replace(signals, site_audit=AUDIT)

    directive = evaluate_technical_health(42, with_audit, generated_at=NOW)
    facts = technician_facts(directive)

    assert directive.mobile_speed.field_evidence == (
        "Utilizatorii reali (Chrome, percentila 75): LCP 2,9 s, INP 240 ms, CLS 0,04."
    )
    assert "- Utilizatorii reali (Chrome, percentila 75): LCP 2,9 s" in facts
    assert "- Audit tehnic SEO/GEO (crawl real al site-ului): Auditul tehnic din" in facts
    assert "- Problemă din audit: Pagini fără titlu (critică, 3 pagini)" in facts
    assert "Auditul SEO/GEO: 2 probleme critice, prima: Pagini fără titlu" in directive.summary
    # Auditul e context: nu schimba starea si nu pune veto.
    without = evaluate_technical_health(42, signals, generated_at=NOW)
    assert (directive.status, directive.veto) == (without.status, without.veto)
    assert "Auditul tehnic SEO/GEO n-a rulat încă" in technician_facts(without)


def _audit_result(*issues: tuple[str, str]) -> AuditResult:
    pages = [
        CrawledPage(url=f"https://autofix.ro/{name}", status_code=200, fetch_class="ok")
        for name in ("", "servicii", "contact")
    ]
    return AuditResult(
        start_url="https://autofix.ro/",
        origin="https://autofix.ro",
        brand="autofix",
        started_at=NOW - timedelta(minutes=2),
        finished_at=NOW,
        completed=True,
        robots_txt_found=True,
        llms_txt_found=False,
        sitemap_urls_found=3,
        pages=pages,
        issues=[DetectedIssue(issue_type=kind, page_url=url) for kind, url in issues],
        scores={
            "seo": PillarScore(81, 20, 3, 40.0, 6.0),
            "geo": PillarScore(60, 10, 4, 20.0, 8.0),
        },
    )


def _kinds(severity: str) -> list[str]:
    return [kind for kind, issue in AUDIT_ISSUE_TYPES.items() if issue.severity == severity]


def test_the_audit_report_is_summarised_worst_first() -> None:
    critical, warning = _kinds("critical")[0], _kinds("warning")[0]
    result = _audit_result(
        (warning, "https://autofix.ro/"),
        (warning, "https://autofix.ro/servicii"),
        (warning, "https://autofix.ro/servicii"),  # aceeasi pagina: o singura data
        (critical, "https://autofix.ro/contact"),
        ("tip-necunoscut", "https://autofix.ro/"),
    )

    snapshot = audit_snapshot(7, result)

    assert (snapshot.seo_score, snapshot.geo_score, snapshot.pages_crawled) == (81, 60, 3)
    assert (snapshot.critical_issues, snapshot.warning_issues, snapshot.info_issues) == (1, 1, 0)
    assert [(item["type"], item["pages"]) for item in snapshot.top_issues] == [
        (critical, 1),
        (warning, 2),
    ]
    first = snapshot.top_issues[0]
    assert first["title"] == AUDIT_ISSUE_TYPES[critical].title
    assert first["fix"] and len(first["fix"]) <= 220 and not first["fix"].endswith(".")


def test_the_nightly_audit_is_stored_for_the_cto(session: Session) -> None:
    account = _client_account(session)
    account.target_domain = "autofix.ro"
    account.brand_name = "autofix"
    session.add(account)
    session.commit()
    asked: list[tuple[str, str]] = []

    def audit(url: str, brand: str) -> AuditResult:
        asked.append((url, brand))
        return _audit_result((_kinds("critical")[0], "https://autofix.ro/contact"))

    result = run_site_audit_job(client_account_id=account.id or 0, audit=audit)

    assert result == {
        "audited": True,
        "url": "https://autofix.ro/",
        "pages": 3,
        "critical_issues": 1,
    }
    assert asked == [("https://autofix.ro/", "autofix")]
    signals = DbTechnicalSignals(session, today=lambda: TODAY).load(account.id or 0)
    assert signals.site_audit is not None
    assert (signals.site_audit.seo_score, signals.site_audit.critical) == (81, 1)
    assert signals.site_audit.issues[0].severity == "critical"


def test_the_nightly_audit_needs_a_public_domain(session: Session) -> None:
    account = _client_account(session)

    assert run_site_audit_job(client_account_id=account.id or 0) == {
        "audited": False,
        "reason": "fara domeniu in Setari",
    }
    account.target_domain = "intranet.local"
    session.add(account)
    session.commit()
    # conftest: auditul real nu ruleaza; un None = adresa refuzata de politica de crawl.
    refused = run_site_audit_job(client_account_id=account.id or 0)
    assert refused["audited"] is False
    assert session.exec(select(SiteAuditSnapshot)).all() == []


def test_the_real_audit_refuses_private_addresses() -> None:
    assert real_run_site_audit("http://127.0.0.1:8000", "") is None


def test_the_nightly_maintenance_runs_the_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        tasks, "run_site_audit_job", lambda *, client_account_id: calls.append(client_account_id)
    )
    for name in ("run_metrics_sync_job", "run_speed_check_job", "run_tracking_contract_job",
                 "run_propose_job", "run_fatigue_check_job"):
        monkeypatch.setattr(tasks, name, lambda *, client_account_id: {})

    result = tasks.run_client_maintenance_job(client_account_id=5)

    assert calls == [5] and "site_audit" in result


def test_crux_fields_are_read_from_the_speed_sample(session: Session) -> None:
    account = _client_account(session)
    session.add(
        SiteSpeedSample(
            client_account_id=account.id or 0,
            url="https://autofix.ro/",
            performance_score=88,
            lcp_ms=2400,
            layout_shift=0.05,
            tbt_ms=150,
            field_lcp_ms=2600,
            field_cls=0.08,
            field_inp_ms=180,
            measured_at=NOW - timedelta(days=1),
        )
    )
    session.commit()

    signals = DbTechnicalSignals(session, today=lambda: TODAY).load(account.id or 0)

    assert signals.mobile_speed is not None
    assert (signals.mobile_speed.field_cls, signals.mobile_speed.field_inp_ms) == (0.08, 180)


# --- consiliul in flux ---------------------------------------------------------------------


class _StreamingVoice(_CouncilVoice):
    """Vocea care scrie in flux: acelasi text, cuvant cu cuvant."""

    def stream(self, *, system: str, user: str) -> Iterator[str]:
        words = self.complete(system=system, user=user).split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else f"{word} "


def test_the_council_tells_its_listener_what_happens_as_it_happens() -> None:
    voice = _StreamingVoice()
    assert isinstance(voice, StreamingTextGenerator)
    events: list[CouncilEvent] = []

    reply = _council(voice=voice).evaluate_client_query(
        "Merită să cresc bugetul?", _directive(), on_event=events.append
    )

    kinds = [event.kind for event in events]
    assert events[0] == CouncilEvent("stage", stage="deliberation")
    assert sorted(e.opinion.member for e in events if e.opinion is not None) == [
        "cfo", "cpo", "strategist"
    ]
    synthesis = kinds.index("stage", 1)
    assert events[synthesis].stage == "synthesis"
    assert all(kind == "token" for kind in kinds[synthesis + 1 :])
    assert "".join(event.text for event in events if event.kind == "token") == CHAIR_SAYS
    assert (reply.source, reply.reply) == ("llm", CHAIR_SAYS)


def test_rebuttals_are_announced_before_they_arrive() -> None:
    events: list[CouncilEvent] = []

    _council(LOSING, voice=_StreamingVoice()).evaluate_client_query(
        "Merită să cresc bugetul?", _directive(), on_event=events.append
    )

    rebuttals = [i for i, event in enumerate(events) if event.kind == "rebuttal"]
    announced = events.index(CouncilEvent("stage", stage="rebuttals"))
    assert rebuttals and announced < rebuttals[0]
    assert events.index(CouncilEvent("stage", stage="synthesis")) > rebuttals[-1]


def test_a_broken_listener_never_breaks_the_answer() -> None:
    def explode(event: CouncilEvent) -> None:
        raise RuntimeError("clientul a inchis conexiunea")

    reply = _council(voice=_StreamingVoice()).evaluate_client_query(
        "Merită să cresc bugetul?", _directive(), on_event=explode
    )
    same = _council(voice=_StreamingVoice()).evaluate_client_query(
        "Merită să cresc bugetul?", _directive()
    )

    assert (reply.source, reply.reply) == (same.source, same.reply)


def test_a_voice_without_streaming_still_answers_with_a_listener() -> None:
    events: list[CouncilEvent] = []

    reply = _council(voice=_CouncilVoice()).evaluate_client_query(
        "Merită să cresc bugetul?", _directive(), on_event=events.append
    )

    assert "token" not in [event.kind for event in events]
    assert (reply.source, reply.reply) == ("llm", CHAIR_SAYS)
