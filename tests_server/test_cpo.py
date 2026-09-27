"""CPO-ul: apara oferta, desparte mesajul de oferta la un CPA mare, pozitioneaza.

Trei scenarii pe acelasi service de cutii automate: reclama tehnica pierde bani
(vina e a mesajului), reclama care ii vorbeste clientului ideal pierde bani (vina
e a ofertei - pivotare doar spre un semnal real din piata) si un segment care
cumpara mult mai usor decat cauta (pozitionarea se poate ascuti).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from ppc_agent_server.services.council import QueenCouncil
from ppc_agent_server.services.cpo import CPO_SYSTEM_PROMPT, evaluate_offer
from ppc_agent_server.services.memory import MAX_MEMORY_CHARS, memory_line
from ppc_agent_server.services.queen_agent import (
    BrandStrategyDirective,
    LiveAd,
    SearchSignal,
)
from ppc_agent_server.services.researcher import (
    MarketDirective,
    MarketSignals,
    build_market_directive,
)
from tests_server.test_memory import _Memory
from tests_server.test_queen_agent import CONVENIENCE_AD, NOW
from tests_server.test_queen_council import (
    LOSING,
    THIN_DIRECTIVE_SIGNALS,
    _ad,
    _council,
    _CouncilVoice,
    _directive,
    _finances,
    _Static,
    _StaticMarket,
    _StaticTechnical,
)
from tests_server.test_researcher import DEMO, LIVE, WEB
from tests_server.test_technician import BROKEN_TAG, GA4_DOWN
from tests_server.test_technician import _signals as _technical

#: Reclama care ii vorbeste clientului ideal («Ocupatul pragmatic») si tot pierde bani.
ALIGNED_LOSER = LiveAd(
    ref="meta_ad/333",
    platform="meta",
    headline=CONVENIENCE_AD.headline,
    body=CONVENIENCE_AD.body,
    spend=Decimal("960"),
    conversions=8,
    target_cpa=Decimal("80"),
)
ALIGNED_FINANCES = _finances(
    ads=(_ad("333", spend="960", conversions=8, label=CONVENIENCE_AD.headline),), terms=()
)
#: Vanatorii de pret cauta cel mai mult; scepticii care vor garantii cumpara.
MISPOSITIONED_SEARCHES = [
    SearchSignal("service cutie automata pret", "paid", 1500, 90, 2.0),
    SearchSignal("schimb ulei cutie automata pret", "organic", 1200, 40),
    SearchSignal("service cutie automata garantie", "paid", 300, 30, 9.0),
    SearchSignal("programare online schimb ulei cutie automata", "paid", 400, 30, 3.0),
]
PIVOT = (
    "Oferta trebuie pivotată: reclama «Programare online în 2 minute | Gata în aceeași zi» îi "
    "vorbește deja lui «Ocupatul pragmatic» și tot pierde bani (CPA 120 RON, peste ținta de "
    "80 RON), deci nu mesajul e problema. Piața caută acum «prețul afișat înainte de "
    "programare» (+56%, după Researcher): acolo mutăm unghiul ofertei."
)
POSITIONING_GAP = (
    "Oferta se poate poziționa mai bine: «Scepticul care vrea garanții» cumpără mai ușor decât "
    "caută (64% din conversii la 9% din căutări), dar mesajul e construit pentru «Vânătorul de "
    "preț» (14% din conversii la 79% din căutări)."
)


def _aligned() -> BrandStrategyDirective:
    return _directive(ads=[ALIGNED_LOSER])


def _market(signals: MarketSignals = LIVE) -> MarketDirective:
    return build_market_directive(42, signals, generated_at=NOW)


# --- verdictul pe oferta (determinist) ----------------------------------------------------------


def test_an_offer_that_fits_is_defended_with_who_buys() -> None:
    product = evaluate_offer(_directive(), unprofitable=False, generated_at=NOW)

    assert product.status == "fit"
    assert product.verdict == (
        "Oferta se potrivește cu piața: «Ocupatul pragmatic» e și cel care cumpără (74% din "
        "conversii la 47% din căutări)."
    )
    assert product.story == (
        "Problema: nu are timp să stea la coadă sau să piardă o zi. Promisiunea: să rezolve "
        "totul din telefon, în două minute. Dovada: programarea online și durata."
    )
    # RICE: 74% din conversii x impact 1 x incredere 80% / o jumatate de saptamana.
    [move] = product.moves
    assert (move.kind, move.reach, move.rice) == ("message", 74, 118)


def test_aligned_ads_that_still_lose_pivot_the_offer_toward_the_rising_pain() -> None:
    product = evaluate_offer(_aligned(), unprofitable=True, market=_market(), generated_at=NOW)

    assert (product.status, product.focus) == ("pivot", "prețul afișat înainte de programare")
    assert product.verdict == PIVOT
    assert product.story.startswith("Problema: piața caută acum «prețul afișat")
    assert [(move.kind, move.rice) for move in product.moves] == [("pivot", 60)]


@pytest.mark.parametrize("market", [None, DEMO], ids=["fara-piata", "piata-demo"])
def test_without_a_real_market_signal_the_offer_is_tested_not_pivoted(
    market: MarketSignals | None,
) -> None:
    directive = _market(market) if market is not None else None
    product = evaluate_offer(_aligned(), unprofitable=True, market=directive, generated_at=NOW)

    assert product.status == "offer_gap"
    assert product.verdict.startswith("Oferta e sub semnul întrebării:")
    assert "deci o testăm, nu o schimbăm" in product.verdict
    assert [move.kind for move in product.moves] == ["offer_test"]


def test_the_segment_that_buys_most_easily_sharpens_the_positioning() -> None:
    directive = _directive(searches=MISPOSITIONED_SEARCHES)

    product = evaluate_offer(directive, unprofitable=False, generated_at=NOW)

    assert (product.status, product.best_fit) == ("positioning_gap", "Scepticul care vrea garanții")
    assert product.verdict == POSITIONING_GAP
    assert product.positioning.startswith(
        "Pentru «Scepticul care vrea garanții», care vrea garanție scrisă pe ce plătește"
    )
    # Repozitionarea atinge 64% din conversii, rescrierea doar 14%: RICE o pune prima.
    assert [(move.kind, move.rice) for move in product.moves] == [
        ("reposition", 51), ("message", 22)
    ]


def test_competitors_found_on_the_web_enter_the_positioning() -> None:
    product = evaluate_offer(
        _directive(), unprofitable=False, market=_market(WEB), generated_at=NOW
    )

    assert product.positioning.endswith(
        "Alternativele pe care le compară (găsite pe web): yably.ro, cylex.ro."
    )


def test_without_an_ideal_client_the_offer_is_not_judged() -> None:
    directive = _directive(**THIN_DIRECTIVE_SIGNALS)

    product = evaluate_offer(directive, unprofitable=True, generated_at=NOW)

    assert (product.status, product.moves) == ("unknown", [])
    reply = _council(voice=_CouncilVoice()).evaluate_client_query("Cine e publicul meu?", directive)
    assert reply.opinions[-1].member == "cpo"
    assert reply.opinions[-1].fallback_reason == "Fără date pentru acest rol - poziția standard."
    assert reply.ruling.offer is None


# --- CPO-ul in consiliu ------------------------------------------------------------------------


def test_on_a_high_cpa_from_the_wrong_message_the_cpo_defends_the_offer() -> None:
    reply = _council(LOSING).evaluate_client_query("Merită să cresc bugetul?", _directive())

    assert reply.product is not None and reply.product.status == "message_gap"
    assert reply.ruling.offer == (
        "Oferta nu e problema: reclama «Schimb ulei ATF cutie automata» nu îi vorbește lui "
        "«Ocupatul pragmatic», deci CPA-ul mare vine din mesaj, nu din ofertă. Întâi "
        "rescrierea, apoi judecăm oferta."
    )
    assert "CPO-ul spune că oferta nu e problema:" in reply.reply
    # Decizia pe bani ramane a CFO-ului.
    assert reply.ruling.decision == "Nu acum: contul nu e rentabil. Întâi se taie ce pierde bani."


def test_the_cpo_reads_the_researcher_signal_and_the_chair_hears_the_pivot() -> None:
    voice = _CouncilVoice()
    reply = QueenCouncil(
        _Static(ALIGNED_FINANCES), market=_StaticMarket(LIVE), voice=voice, clock=lambda: NOW
    ).evaluate_client_query("De ce nu vând reclamele?", _aligned())

    assert reply.ruling.offer == PIVOT
    cpo = voice.prompt("cpo")
    assert "FAPTE DE PRODUS" in cpo and "Mutarea 1 după RICE: pivotarea unghiului" in cpo
    assert "Verdict financiar" not in cpo
    chair = voice.prompt("chair")
    assert "PĂREREA CPO-ULUI" in chair
    assert f"Verdictul CPO-ului pe ofertă: {PIVOT}" in chair
    assert CPO_SYSTEM_PROMPT.index("6. Verifică CONTEXTUL ISTORIC") > 0


def test_a_positioning_gap_is_said_on_audience_questions_not_on_budget() -> None:
    directive = _directive(searches=MISPOSITIONED_SEARCHES)

    audience = _council().evaluate_client_query("Cine e publicul meu?", directive)
    budget = _council().evaluate_client_query("Merită să cresc bugetul?", directive)

    assert audience.ruling.offer == POSITIONING_GAP
    assert "CPO-ul spune că oferta se poate poziționa mai bine" in audience.reply
    assert budget.ruling.offer is None


def test_targeting_ideas_read_as_noun_phrases_in_the_reply_the_ruling_and_the_memory() -> None:
    memory = _Memory()
    council = QueenCouncil(_Static(LOSING), memory=memory, clock=lambda: NOW)

    reply = council.evaluate_client_query(
        "De ce a crescut costul pe client luna asta?", _directive(searches=MISPOSITIONED_SEARCHES)
    )

    # Imperativul e pentru agentie («Caută ...»); in frazele consiliului intra forma nominala.
    assert "a tăiat caută" not in reply.reply.lower()
    assert (
        "CFO-ul a tăiat un test de interese apropiate de «automata», «cutie», «service», ca set "
        "separat: cere buget în plus, iar contul nu e rentabil." in reply.reply
    )
    assert (
        "butonul «Vezi prețurile» (sau un formular de ofertă) și reclame cu prețul în imagine: "
        "nu adaugă cheltuieli"
    ) in reply.ruling.approved
    [cfo] = [entry for entry in memory.written if entry.role == "cfo"]
    assert cfo.decision == (
        "a tăiat un test de interese apropiate de «automata», «cutie», «service», ca set "
        "separat, pentru că cere buget în plus, iar contul nu e rentabil"
    )


def test_broken_tracking_never_triggers_a_pivot() -> None:
    council = QueenCouncil(
        _Static(ALIGNED_FINANCES),
        technical=_StaticTechnical(_technical(BROKEN_TAG, evidence=GA4_DOWN)),
        market=_StaticMarket(LIVE),
        clock=lambda: NOW,
    )

    reply = council.evaluate_client_query("De ce nu vând reclamele?", _aligned())

    assert reply.product is not None
    assert (reply.product.cpa_alarm, reply.product.status) == (False, "fit")
    assert reply.ruling.offer is None


# --- memoria ----------------------------------------------------------------------------------


def test_the_cpo_pivot_is_remembered_compressed_and_recalled_later() -> None:
    memory = _Memory()

    def council(days: int) -> QueenCouncil:
        return QueenCouncil(
            _Static(ALIGNED_FINANCES),
            market=_StaticMarket(LIVE),
            memory=memory,
            clock=lambda: NOW + timedelta(days=days),
        )

    council(0).evaluate_client_query("Merită să cresc bugetul?", _aligned())

    [cpo] = [entry for entry in memory.written if entry.role == "cpo"]
    assert cpo.decision == (
        "a propus pivotarea ofertei spre «prețul afișat înainte de programare», după "
        "framework-ul de poziționare"
    )
    assert cpo.observation.startswith("reclama «Programare online în 2 minute")
    assert len(cpo.observation) <= MAX_MEMORY_CHARS
    assert memory_line(cpo, NOW + timedelta(days=14)).startswith(
        "Acum 2 săptămâni, CPO-ul a propus pivotarea ofertei spre «prețul afișat"
    )

    later = council(14).evaluate_client_query("Cine e publicul meu?", _aligned())
    assert any(line.startswith("Acum 2 săptămâni, CPO-ul a propus") for line in later.history)
