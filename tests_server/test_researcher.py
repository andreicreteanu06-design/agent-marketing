"""Researcher-ul (CSO): contextul pietei, determinist, si locul lui in consiliu.

Regulile se verifica pe semnale construite in test. Sursele sunt doar reale (Google
Trends, cautarea pe web); fara ele, nimic nu se inventeaza: piata ramane necunoscuta,
iar Researcher-ul spune ce lipseste, fara LLM. Google Trends are testele lui in
``test_market_trends.py``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.services.council import QuestionTopic, classify_question
from ppc_agent_server.services.humanizer import ai_tells
from ppc_agent_server.services.market_trends import TrendPoint, TrendsUnavailableError
from ppc_agent_server.services.queen_signals import ClientMarketSignals
from ppc_agent_server.services.researcher import (
    RELEVANCE_QUESTION,
    AuctionSnapshot,
    CompetitorMove,
    DemandSeries,
    MarketDirective,
    MarketResearcher,
    MarketSignals,
    PainTopic,
    WebFinding,
    build_market_directive,
    competitor_activity,
    has_market_data,
    market_facts,
    market_focus,
    market_trend,
    search_market_web,
    social_sentiment,
)
from ppc_agent_server.skills import BaseAgentSkill, SkillRegistry, web_search
from tests_server.llm_fakes import FakeJev
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_agent import NOW
from tests_server.test_queen_council import _council, _CouncilVoice, _directive
from tests_server.test_queen_router import signed_in  # noqa: F401 - fixture

TODAY = NOW.date()  # 25 septembrie: octombrie e varf de sezon in indicele de mai jos

#: Sezonul unui service auto, ianuarie..decembrie (media anului = 1): schimbul de
#: anvelope urca martie-aprilie si octombrie-noiembrie.
SEASON_INDEX = (0.82, 0.78, 1.02, 1.22, 1.04, 0.95, 0.90, 0.84, 1.00, 1.24, 1.18, 1.01)

AUCTION = AuctionSnapshot(
    competitors_before=5,
    competitors_now=7,
    cpc_before=Decimal("2.10"),
    cpc_now=Decimal("2.65"),
    client_share_before=0.31,
    client_share_now=0.24,
    movers=(
        CompetitorMove("Concurentul B", 0.12, 0.24),
        CompetitorMove("Concurentul C", 0.2, 0.19),
    ),
)
DEMAND = DemandSeries(
    category="service auto",
    weekly=[1000, 1010, 1020, 1030, 1120, 1150, 1170, 1190],
    same_weeks_last_year=4200,
    monthly_index=SEASON_INDEX,
)
PAINS = (
    PainTopic("prețul afișat înainte de programare", "cat costa diagnoza auto", 90, 140),
    PainTopic("garanție la manoperă", "service auto cu garantie", 80, 82),
    # Creste mult, dar din prea putine mentiuni: zgomot.
    PainTopic("programare în weekend", "service auto sambata", 10, 19),
)
LIVE = MarketSignals(
    market="service auto, București",
    today=TODAY,
    period_days=28,
    auction=AUCTION,
    demand=DEMAND,
    pains=PAINS,
)
#: Nisa necunoscuta: nicio sursa n-a avut ce masura - si nimic nu se inventeaza.
NO_MARKET = MarketSignals(
    market="România", today=TODAY, period_days=28, auction=None, demand=None, location="România"
)
#: Cererea din Google Trends: indice 0-100, nu cautari.
TRENDS_DEMAND = replace(
    DEMAND,
    weekly=[50, 52, 51, 53, 60, 62, 61, 63],
    same_weeks_last_year=210,
    unit="index",
    source="Google Trends",
)


def _directive_for(signals: MarketSignals) -> MarketDirective:
    return build_market_directive(42, signals, generated_at=NOW)


# --- concurenta ---------------------------------------------------------------------------


def test_new_entrants_that_push_the_cpc_up_are_rising_pressure() -> None:
    activity = competitor_activity(AUCTION, period_days=28)

    assert activity.pressure == "rising"
    assert activity.evidence == (
        "CPC-ul mediu din licitație a mers de la 2,10 la 2,65 RON (+26%) în ultimele 28 de zile. "
        "Au intrat 2 concurenți noi (7 față de 5). Concurentul B și-a urcat cota de afișări de "
        "la 12% la 24%. Cota ta de afișări a scăzut cu 7 puncte: de la 31% la 24%."
    )
    assert activity.implication.startswith("CPC-ul urcă din cauza concurenței.")
    assert (activity.top_mover, activity.cpc_change) == ("Concurentul B", 0.2619)


def test_one_aggressive_competitor_is_enough_for_pressure() -> None:
    auction = replace(AUCTION, competitors_now=5)

    assert competitor_activity(auction, period_days=28).pressure == "rising"


def test_a_pricier_click_without_market_movers_is_not_blamed_on_competitors() -> None:
    calm = (CompetitorMove("Concurentul B", 0.2, 0.21),)
    auction = replace(AUCTION, competitors_now=5, movers=calm)

    activity = competitor_activity(auction, period_days=28)

    assert activity.pressure == "stable"
    assert activity.implication == "Licitația e stabilă. Dacă CPC-ul tău se mișcă, cauza e în cont."
    assert activity.top_mover is None


def test_a_cheaper_auction_with_no_new_entrants_is_easing() -> None:
    auction = replace(AUCTION, competitors_now=4, cpc_now=Decimal("1.80"), movers=())

    activity = competitor_activity(auction, period_days=28)

    assert activity.pressure == "easing"
    assert "Au ieșit concurenți (4 față de 5)." in activity.evidence


def test_without_auction_data_pressure_is_unknown() -> None:
    activity = competitor_activity(None, period_days=28)

    assert (activity.pressure, activity.cpc_change, activity.top_mover) == ("unknown", None, None)


# --- cererea si sezonul ----------------------------------------------------------------------


def test_growing_demand_before_the_peak_is_a_window_of_opportunity() -> None:
    trend = market_trend(DEMAND, today=TODAY)

    assert (trend.direction, trend.season) == ("growing", "rising")
    assert (trend.change, trend.year_over_year) == (0.1404, 0.1024)
    assert trend.evidence == (
        "Căutări pentru «service auto»: 4630 de căutări în ultimele 4 săptămâni, +14% față de "
        "cele 4 dinainte și +10% față de anul trecut. Sezonul urcă: octombrie e de obicei peste "
        "luna asta."
    )
    assert trend.window.startswith(
        "Fereastră de oportunitate: cererea urcă înainte de vârful din octombrie."
    )


@pytest.mark.parametrize(
    ("today", "weekly", "direction", "season", "window"),
    [
        (date(2026, 10, 10), [1000] * 8, "flat", "peak", "Vârf de sezon"),
        (date(2026, 12, 10), [1200] * 4 + [1000] * 4, "declining", "cooling", "Piața se strânge"),
        (date(2026, 2, 10), [1000] * 8, "flat", "rising", "Fereastră de oportunitate"),
        (date(2026, 6, 10), [1000] * 8, "flat", "normal", "Cerere stabilă"),
        (date(2026, 1, 10), [1000] * 8, "flat", "low", "Piața se strânge"),
    ],
)
def test_the_season_and_the_trend_decide_the_window(
    today: date, weekly: list[int], direction: str, season: str, window: str
) -> None:
    trend = market_trend(replace(DEMAND, weekly=weekly, same_weeks_last_year=None), today=today)

    assert (trend.direction, trend.season, trend.year_over_year) == (direction, season, None)
    assert trend.window.startswith(window)


def test_a_google_trends_series_speaks_in_index_points_not_searches() -> None:
    trend = market_trend(TRENDS_DEMAND, today=TODAY)

    assert (trend.direction, trend.season) == ("growing", "rising")
    assert (trend.change, trend.year_over_year) == (0.1942, 0.1714)
    assert trend.evidence.startswith(
        "Interesul de căutare pentru «service auto» (Google Trends): indice mediu 61,5 din 100 "
        "în ultimele 4 săptămâni, +19% față de cele 4 dinainte și +17% față de anul trecut."
    )
    assert "căutări în ultimele" not in trend.evidence


def test_a_short_series_has_no_trend() -> None:
    trend = market_trend(replace(DEMAND, weekly=[1000] * 5), today=TODAY)

    assert (trend.direction, trend.season, trend.change) == ("unknown", "unknown", None)


# --- ce cauta piata -------------------------------------------------------------------------


def test_only_pains_that_grow_from_enough_mentions_count() -> None:
    sentiment = social_sentiment(PAINS, period_days=28)

    assert [(pain.theme, pain.growth, pain.mentions) for pain in sentiment.rising] == [
        ("prețul afișat înainte de programare", 0.5556, 140)
    ]
    assert sentiment.evidence == (
        "Crește «prețul afișat înainte de programare»: +56%, 140 de mențiuni în ultimele 28 de "
        "zile (de exemplu «cat costa diagnoza auto»)."
    )


def test_a_quiet_market_says_so() -> None:
    assert "aceleași lucruri" in social_sentiment(PAINS[1:2], period_days=28).evidence
    assert "Nu am date" in social_sentiment((), period_days=28).evidence


# --- directiva ------------------------------------------------------------------------------


def test_the_directive_puts_competitors_demand_and_pains_together() -> None:
    directive = MarketResearcher(_Static(LIVE), clock=lambda: NOW).evaluate_market_context(42)

    assert directive.generated_at == NOW
    assert has_market_data(directive)
    assert directive.opportunity.endswith(
        "Mesajul care prinde acum: «prețul afișat înainte de programare»."
    )
    assert directive.summary.startswith("Concurența: presiune în creștere. CPC-ul mediu")
    assert "Cererea: în creștere." in directive.summary
    assert directive.notes == []


def test_without_sources_nothing_is_invented() -> None:
    directive = _directive_for(NO_MARKET)

    assert directive.competitor_activity.pressure == "unknown"
    assert (directive.market_trend.direction, directive.market_trend.season) == (
        "unknown",
        "unknown",
    )
    assert directive.social_sentiment.rising == []
    assert not has_market_data(directive)
    # Nu mai exista date demonstrative, deci nici marcajul lor.
    assert not {"source", "is_demo"} & set(directive.model_dump())


def test_no_researcher_text_sounds_generated() -> None:
    texts: list[str] = []
    for signals in (
        LIVE,
        NO_MARKET,
        replace(LIVE, auction=None, demand=TRENDS_DEMAND, pains=()),
        replace(LIVE, auction=None, demand=None, pains=()),
    ):
        directive = _directive_for(signals)
        texts.extend([directive.summary, market_facts(directive), directive.opportunity])
    assert [(text[:60], ai_tells(text)) for text in texts if ai_tells(text)] == []


# --- in consiliu ----------------------------------------------------------------------------


class _Static:
    def __init__(self, signals: MarketSignals) -> None:
        self._signals = signals

    def load(self, client_account_id: int, queries: Sequence[str] = ()) -> MarketSignals:
        return self._signals


QUESTION = "Merită să cresc bugetul?"


def test_without_market_data_the_researcher_says_so_without_an_llm() -> None:
    voice = _CouncilVoice()
    reply = _council(voice=voice, market=NO_MARKET).evaluate_client_query(QUESTION, _directive())
    without = _council(voice=_CouncilVoice()).evaluate_client_query(QUESTION, _directive())

    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "researcher"]
    assert opinion.source == "template"
    assert opinion.fallback_reason is not None and opinion.fallback_reason.startswith("Fără date")
    assert reply.market is not None and opinion.opinion == reply.market.summary
    assert reply.ruling.market_context is None
    assert reply.ruling == without.ruling
    assert voice.roles == ["chair"]
    assert "FAPTE DE PIAȚĂ" not in voice.prompt("chair")


def test_an_unknown_market_stays_out_of_the_deterministic_reply() -> None:
    reply = _council(market=NO_MARKET).evaluate_client_query(QUESTION, _directive())
    without = _council().evaluate_client_query(QUESTION, _directive())

    assert reply.reply == without.reply


def test_live_market_context_explains_a_budget_decision() -> None:
    reply = _council(market=LIVE).evaluate_client_query(QUESTION, _directive())

    context = reply.ruling.market_context
    assert context is not None
    assert context.startswith("CPC-ul urcă din cauza concurenței.")
    assert "Fereastră de oportunitate" in context
    assert context in reply.reply
    # Contextul nu muta nicio idee.
    without = _council().evaluate_client_query(QUESTION, _directive()).ruling
    assert (reply.ruling.approved, reply.ruling.cut) == (without.approved, without.cut)


def test_live_market_gives_creative_questions_the_rising_pain() -> None:
    reply = _council(market=LIVE).evaluate_client_query(
        "Ce text să pun în reclame?", _directive()
    )

    assert reply.ruling.market_context == (
        "Piața caută acum «prețul afișat înainte de programare»: un unghi pentru textele noi."
    )


CPC_QUESTION = "De ce a crescut costul pe click (CPC) luna asta?"


@pytest.mark.parametrize(
    "question", [CPC_QUESTION, "De ce s-a scumpit prețul pe click?", "CPC-ul e prea mare"]
)
def test_click_price_questions_are_about_the_auction(question: str) -> None:
    assert classify_question(question, active_platforms=set()) == QuestionTopic(
        "profitability", about_cpc=True
    )


def test_a_live_auction_answers_why_the_click_got_pricier() -> None:
    reply = _council(market=LIVE).evaluate_client_query(CPC_QUESTION, _directive())

    decision = reply.ruling.decision
    assert decision.startswith("CPC-ul mediu din licitație a mers de la 2,10 la 2,65 RON (+26%)")
    assert "CPC-ul urcă din cauza concurenței." in decision
    assert "Ce contează e costul pe client. Contul e rentabil" in decision
    # Licitatia e deja in decizie: contextul pietei nu o repeta.
    assert reply.ruling.market_context is not None
    assert reply.ruling.market_context.startswith("Fereastră de oportunitate")


def test_without_real_auction_data_the_council_says_what_is_missing() -> None:
    reply = _council(market=NO_MARKET).evaluate_client_query(CPC_QUESTION, _directive())

    assert reply.ruling.decision.startswith("De ce s-a scumpit click-ul nu pot spune încă")
    assert "Concurentul" not in reply.reply


def test_a_live_researcher_gives_its_position_and_the_chair_the_market_facts() -> None:
    voice = _CouncilVoice()
    reply = _council(voice=voice, market=LIVE).evaluate_client_query(QUESTION, _directive())

    assert voice.roles == ["chair"]
    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "researcher"]
    assert reply.market is not None
    assert (opinion.source, opinion.opinion) == ("template", reply.market.summary)
    assert opinion.fallback_reason is None
    chair = voice.prompt("chair")
    assert f"- Researcher-ul (piața): {opinion.opinion}" in chair
    assert "Contextul pieței (Researcher): CPC-ul urcă" in chair
    assert "FAPTE DE PIAȚĂ" not in chair  # faptele brute raman la Researcher


# --- sursa si ruta ----------------------------------------------------------------------------


class _Trends:
    """Google Trends din teste: seria data sau o eroare, plus ce s-a cerut."""

    def __init__(
        self, points: list[TrendPoint] | None = None, error: Exception | None = None
    ) -> None:
        self.points = points or []
        self.error = error
        self.asked: list[tuple[str, str]] = []

    def weekly_interest(self, keyword: str, *, geo: str) -> list[TrendPoint]:
        self.asked.append((keyword, geo))
        if self.error is not None:
            raise self.error
        return self.points


def _weeks(values: Sequence[int]) -> list[TrendPoint]:
    """Saptamani consecutive care se termina pe 20 septembrie 2026."""
    first = date(2026, 9, 20).toordinal() - 7 * (len(values) - 1)
    return [
        TrendPoint(week=date.fromordinal(first + 7 * index), value=value)
        for index, value in enumerate(values)
    ]


def test_without_the_client_searches_nothing_is_searched_or_invented(session: Session) -> None:
    account = _client_account(session)
    trends = _Trends(_weeks([50] * 60))

    signals = ClientMarketSignals(session, today=lambda: TODAY, trends=trends).load(
        account.id or 0
    )

    assert (signals.auction, signals.demand, tuple(signals.pains)) == (None, None, ())
    # Fara cautarile clientului nu exista nisa - deci nicio cautare, nici in Trends.
    assert (signals.niche, signals.location, signals.web_status) == ("", "România", "off")
    assert signals.web_note.startswith("Nișa nu se poate deduce încă")
    assert trends.asked == []
    with pytest.raises(LookupError):
        ClientMarketSignals(session).load(999_999)


# --- cautarea pe web ---------------------------------------------------------------------------

SERVICE_QUERIES = [
    "service auto bucuresti",
    "service auto sector 3 pret",
    "revizie service auto",
    "itp bucuresti",
]


def _found(query: str, *sources: str) -> list[WebFinding]:
    return [
        WebFinding(
            query=query, title=f"Titlu {source}", snippet=f"Fragment {source}", source=source
        )
        for source in sources
    ]


@pytest.mark.parametrize(
    ("queries", "expected"),
    [
        (SERVICE_QUERIES, ("service auto", "București")),
        (
            ["cafenea specialty cluj", "cafenea specialty centru"],
            ("cafenea specialty", "Cluj-Napoca"),
        ),
        (["schimb ulei cutie automata pret", "schimb ulei cutie automata langa mine"],
         ("schimb ulei cutie automata", "România")),
        ([], ("", "România")),
    ],
)
def test_the_niche_and_city_come_from_the_client_searches(
    queries: list[str], expected: tuple[str, str]
) -> None:
    assert market_focus(queries) == expected


def test_the_brand_is_never_the_niche() -> None:
    assert market_focus(["autofix pitesti", "autofix program"], brand="autofix") == (
        "", "Pitești"
    )


class _FakeSearch(BaseAgentSkill):
    """Abilitatea ``web_search`` din teste: o functie in loc de DuckDuckGo."""

    name = "web_search"
    description = "Căutare falsă, pentru teste."

    def __init__(self, search: Callable[[str], list[WebFinding]]) -> None:
        self._search = search

    async def execute(self, **kwargs: Any) -> list[WebFinding]:
        return await asyncio.to_thread(self._search, kwargs["query"])


def _skills(search: Callable[[str], list[WebFinding]]) -> SkillRegistry:
    return SkillRegistry([_FakeSearch(search)])


def test_two_real_searches_give_up_to_five_distinct_local_sources() -> None:
    asked: list[str] = []

    def search(query: str) -> list[WebFinding]:
        asked.append(query)
        return _found(query, "yably.ro", "cylex.ro", "homerun.ro", "a.ro", "b.ro")

    findings, status, note = asyncio.run(
        search_market_web("service auto", "București", year=2026, registry=_skills(search))
    )

    assert sorted(asked) == [
        "competitori service auto București",
        "trenduri service auto România 2026",
    ]
    assert (status, note) == ("ok", "")
    assert [finding.source for finding in findings] == [
        "yably.ro", "cylex.ro", "homerun.ro", "a.ro", "b.ro"
    ]


def test_one_failed_search_does_not_lose_the_other() -> None:
    def search(query: str) -> list[WebFinding]:
        if query.startswith("trenduri"):
            raise ConnectionError("rate limit")
        return _found(query, "yably.ro")

    findings, status, _ = asyncio.run(
        search_market_web("service auto", "București", year=2026, registry=_skills(search))
    )

    assert (status, [finding.source for finding in findings]) == ("ok", ["yably.ro"])


def test_a_hanging_search_times_out_gracefully() -> None:
    def search(query: str) -> list[WebFinding]:
        time.sleep(0.5)
        return _found(query, "yably.ro")

    findings, status, note = asyncio.run(
        search_market_web(
            "service auto", "București", year=2026, registry=_skills(search), timeout=0.05
        )
    )

    assert (findings, status) == ([], "failed")
    assert note.startswith("Căutarea pe web n-a răspuns acum")


def test_a_search_with_no_results_says_so() -> None:
    findings, status, note = asyncio.run(
        search_market_web(
            "service auto", "București", year=2026, registry=_skills(lambda query: [])
        )
    )

    assert (findings, status) == ([], "empty")
    assert note == "Căutarea pe web n-a găsit nimic despre «service auto» în București."


def _about_car_service(state: dict[str, Any], qid: str) -> float:
    """Jev-ul fals: "da" doar pentru fragmentele despre service-uri auto."""
    return 0.92 if "service" in state["search_result"]["title"].lower() else 0.08


def _mixed_results(query: str) -> list[WebFinding]:
    return [
        WebFinding(query=query, title="Service auto Titan", snippet="Revizii.", source="titan.ro"),
        WebFinding(query=query, title="Rețete de clătite", snippet="Făină.", source="retete.ro"),
    ]


def test_jev_keeps_only_the_snippets_about_the_niche(fake_jev: FakeJev) -> None:
    fake_jev.noul_rule = _about_car_service

    findings, status, note = asyncio.run(
        search_market_web(
            "service auto",
            "București",
            year=2026,
            registry=_skills(_mixed_results),
            verifier=fake_jev.router(),
        )
    )

    assert (status, note) == ("ok", "")
    assert [finding.source for finding in findings] == ["titan.ro"]
    # O cerere per fragment (2 interogari x 2 fragmente), cu state-ul minim: nisa + fragmentul.
    assert len(fake_jev.requests) == 4
    request = fake_jev.requests[0]
    assert request["questions"] == {"verify": RELEVANCE_QUESTION.payload()}
    assert set(request["state"]) == {"client_niche", "search_result"}
    assert request["state"]["client_niche"] == "service auto"
    assert set(request["state"]["search_result"]) == {"title", "snippet", "site"}


def test_when_jev_finds_nothing_relevant_the_search_says_so(fake_jev: FakeJev) -> None:
    fake_jev.noul_rule = lambda state, qid: 0.05

    findings, status, note = asyncio.run(
        search_market_web(
            "service auto",
            "București",
            year=2026,
            registry=_skills(_mixed_results),
            verifier=fake_jev.router(),
        )
    )

    assert (findings, status) == ([], "empty")
    assert note == "Căutarea pe web n-a găsit nimic relevant despre «service auto» în București."


def test_without_an_answer_from_jev_every_snippet_stays(fake_jev: FakeJev) -> None:
    fake_jev.status = 500

    findings, status, _ = asyncio.run(
        search_market_web(
            "service auto",
            "București",
            year=2026,
            registry=_skills(_mixed_results),
            verifier=fake_jev.router(),
        )
    )

    assert status == "ok"
    assert [finding.source for finding in findings] == ["titan.ro", "retete.ro"]


def test_a_slow_jev_never_holds_the_search(fake_jev: FakeJev) -> None:
    def slow(state: dict[str, Any], qid: str) -> float:
        time.sleep(0.5)
        return 0.05

    fake_jev.noul_rule = slow

    findings, status, _ = asyncio.run(
        search_market_web(
            "service auto",
            "București",
            year=2026,
            registry=_skills(_mixed_results),
            verifier=fake_jev.router(),
            timeout=0.1,
        )
    )

    assert status == "ok"
    assert len(findings) == 2  # verificarea n-a venit la timp: raman toate


def test_ddgs_results_become_cited_findings_cached_for_the_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def ddgs(query: str) -> list[dict[str, str]]:
        calls.append(query)
        return [
            {
                "title": "Top service-uri auto în Bucureşti",
                "href": "https://www.cylex.ro/service-auto/",
                "body": "Găsește informații   exacte despre service-uri auto.",
            },
            {"title": "", "href": "https://gol.ro/", "body": "fara titlu"},
        ]

    # Registrul implicit: Researcher-ul -> abilitatea web_search -> DuckDuckGo.
    monkeypatch.setattr(web_search, "ddgs_text", ddgs)
    for _ in range(2):
        findings, status, _ = asyncio.run(search_market_web("service auto", "București", year=2026))

    assert status == "ok"
    assert findings == [
        WebFinding(
            query="competitori service auto București",
            title="Top service-uri auto în Bucureşti",
            snippet="Găsește informații exacte despre service-uri auto.",
            source="cylex.ro",
        )
    ]
    assert len(calls) == 2  # doua interogari, o singura data pe zi


def test_the_loader_searches_the_niche_and_city_of_the_client(session: Session) -> None:
    account = _client_account(session)
    seen: list[str] = []

    def search(query: str) -> list[WebFinding]:
        seen.append(query)
        return _found(query, "yably.ro")

    trends = _Trends(_weeks([40] * 52 + [50, 52, 51, 53, 60, 62, 61, 63]))

    signals = ClientMarketSignals(
        session, today=lambda: TODAY, registry=_skills(search), trends=trends
    ).load(account.id or 0, SERVICE_QUERIES)

    assert (signals.niche, signals.location, signals.web_status) == (
        "service auto",
        "București",
        "ok",
    )
    assert "competitori service auto București" in seen
    # Cererea: Google Trends pe nisa, in tara clientului - reala, nu demonstrativa.
    assert trends.asked == [("service auto", "RO")]
    assert signals.demand is not None
    assert (signals.demand.unit, signals.demand.source) == ("index", "Google Trends")
    assert signals.demand.weekly[-8:] == [50, 52, 51, 53, 60, 62, 61, 63]
    assert (signals.market, signals.auction, signals.notes) == (
        "service auto, București",
        None,
        [],
    )
    directive = build_market_directive(account.id or 0, signals, generated_at=NOW)
    assert directive.market_trend.direction == "growing"


def test_when_google_trends_refuses_the_demand_stays_unknown(session: Session) -> None:
    account = _client_account(session)
    refused = TrendsUnavailableError("Google Trends n-a răspuns (TooManyRequestsError)")
    trends = _Trends(error=refused)

    signals = ClientMarketSignals(
        session, today=lambda: TODAY, registry=_skills(lambda query: []), trends=trends
    ).load(account.id or 0, SERVICE_QUERIES)

    assert signals.demand is None
    [note] = signals.notes
    assert note.startswith("Google Trends nu a răspuns acum pentru «service auto»")
    directive = build_market_directive(account.id or 0, signals, generated_at=NOW)
    assert directive.market_trend.direction == "unknown"
    assert not has_market_data(directive)


def test_a_hanging_google_trends_never_holds_the_researcher(session: Session) -> None:
    account = _client_account(session)

    class _Slow(_Trends):
        def weekly_interest(self, keyword: str, *, geo: str) -> list[TrendPoint]:
            time.sleep(0.5)
            return _weeks([50] * 60)

    signals = ClientMarketSignals(
        session,
        today=lambda: TODAY,
        registry=_skills(lambda query: []),
        trends=_Slow(),
        trends_wait=0.05,
    ).load(account.id or 0, SERVICE_QUERIES)

    assert signals.demand is None
    assert signals.notes[0].startswith("Google Trends n-a răspuns în 0 s")


def test_the_loader_passes_the_jev_verifier_to_the_search(
    session: Session, fake_jev: FakeJev
) -> None:
    account = _client_account(session)
    fake_jev.noul_rule = _about_car_service

    signals = ClientMarketSignals(
        session,
        today=lambda: TODAY,
        registry=_skills(_mixed_results),
        verifier=fake_jev.router(),
        trends=_Trends(),
    ).load(account.id or 0, SERVICE_QUERIES)

    assert [finding.source for finding in signals.web] == ["titan.ro"]
    assert fake_jev.requests


WEB = replace(
    NO_MARKET,
    market="service auto, București",
    niche="service auto",
    location="București",
    web=_found("competitori service auto București", "yably.ro", "cylex.ro"),
    web_status="ok",
)


def test_real_web_findings_reach_the_synthesis_without_invented_numbers() -> None:
    voice = _CouncilVoice()
    reply = _council(voice=voice, market=WEB).evaluate_client_query(QUESTION, _directive())

    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "researcher"]
    assert opinion.source == "template" and "yably.ro" in opinion.opinion
    # Sursele ajung la sinteza citate in pozitia Researcher-ului, nu ca fragmente brute.
    chair = voice.prompt("chair")
    assert f"- Researcher-ul (piața): {opinion.opinion}" in chair
    assert "Rezultatul 1 (yably.ro)" not in chair and "Concurentul" not in chair
    # Fragmentele nu muta decizia.
    assert reply.ruling.market_context is None


def test_without_a_voice_the_researcher_cites_the_web_sources() -> None:
    reply = _council(market=WEB).evaluate_client_query(QUESTION, _directive())

    [opinion] = [opinion for opinion in reply.opinions if opinion.member == "researcher"]
    assert opinion.source == "template"
    assert "Pe web, pentru «service auto» în București: 2 surse locale." in opinion.opinion
    assert "yably.ro: «Titlu yably.ro» - Fragment yably.ro" in opinion.opinion


@pytest.mark.parametrize(
    "generic",
    [
        "Faceți growth hacking, ca în Silicon Valley.",
        "Gândiți ca un startup: testați repede.",
    ],
)
def test_generic_business_advice_is_rejected(generic: str) -> None:
    voice = _CouncilVoice({"chair": generic})
    reply = _council(voice=voice, market=WEB).evaluate_client_query(QUESTION, _directive())

    assert reply.source == "template"
    assert reply.fallback_reason is not None and "sfaturi generice" in reply.fallback_reason


Signed = tuple[TestClient, FastAPI, dict[str, str], int]


@pytest.fixture
def market_client(signed_in: Signed) -> Iterator[Signed]:  # noqa: F811
    yield signed_in


def test_the_market_route_returns_only_measured_context(market_client: Signed) -> None:
    client, _, headers, account_id = market_client

    response = client.get("/api/v1/queen/market", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_account_id"] == account_id
    assert not {"source", "is_demo"} & set(body)
    # In teste, DuckDuckGo si Google Trends "pica" (conftest): nimic nu se inventeaza.
    assert body["competitor_activity"]["pressure"] == "unknown"
    assert body["market_trend"]["direction"] == "unknown"
    assert not any(note.startswith("Date demonstrative") for note in body["notes"])
    assert client.get("/api/v1/queen/market").status_code == 401
