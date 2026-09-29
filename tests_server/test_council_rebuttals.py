"""Runda de replici: cine pierde o disputa ii raspunde, o data, celui care a castigat-o.

Disputele le transeaza regulile (``rule_on_question``) - decizia nu se negociaza. Runda
a doua spune ce ramane valabil pentru cel care a pierdut si CAND se rediscuta: o conditie
masurabila, din date, care ajunge si in raspunsul catre client.
"""

from __future__ import annotations

from ppc_agent_server.services.council import (
    QueenCouncil,
    QuestionTopic,
    build_financial_snapshot,
    rule_on_question,
)
from tests_server.test_cpo import ALIGNED_FINANCES, _aligned
from tests_server.test_queen_agent import NOW
from tests_server.test_queen_council import (
    LOSING,
    _council,
    _CouncilVoice,
    _directive,
    _finances,
    _Static,
    _StaticMarket,
    _StaticTechnical,
)
from tests_server.test_researcher import LIVE
from tests_server.test_technician import BROKEN_TAG, GA4_DOWN
from tests_server.test_technician import _signals as _technical

TARGET_REACHED = "CPA-ul contului coboară sub ținta de 80 RON"


# --- disputele, transate determinist -------------------------------------------------------


def test_a_brand_idea_cut_by_the_cfo_is_a_dispute_with_a_measurable_way_back() -> None:
    ruling = rule_on_question(
        QuestionTopic("budget"), _directive(), build_financial_snapshot(LOSING)
    )

    [conflict] = ruling.conflicts
    assert (conflict.kind, conflict.challenger, conflict.respondent) == (
        "money_vs_brand", "strategist", "cfo"
    )
    assert conflict.issue.startswith("un test de interese apropiate de")
    assert conflict.rule.startswith("Când brandul și banii nu se împacă, câștigă CFO-ul")
    assert conflict.reopen_when == ruling.reopen_when == TARGET_REACHED
    assert conflict.rebuttal.startswith("Accept tăierea CFO-ului: un test de interese")
    assert conflict.rebuttal.endswith(f"Revin cu ideea când {TARGET_REACHED}.")


def test_the_way_back_follows_what_the_cfo_measured() -> None:
    no_data = rule_on_question(
        QuestionTopic("budget"), _directive(), build_financial_snapshot(_finances(ads=(), terms=()))
    )
    assert no_data.reopen_when == "contul strânge cel puțin 5 conversii și se dovedește rentabil"


def test_without_a_dispute_there_is_no_second_round() -> None:
    ruling = rule_on_question(
        QuestionTopic("budget"), _directive(), build_financial_snapshot(_finances())
    )
    assert (ruling.conflicts, ruling.reopen_when) == ([], None)

    reply = _council().evaluate_client_query("Merită să cresc bugetul?", _directive())
    assert reply.rebuttals == []
    assert "Se rediscută" not in reply.reply


def test_a_rising_market_and_a_blamed_offer_are_disputes_too() -> None:
    council = QueenCouncil(
        _Static(ALIGNED_FINANCES), market=_StaticMarket(LIVE), clock=lambda: NOW
    )

    reply = council.evaluate_client_query("De ce nu vând reclamele?", _aligned())

    assert [conflict.kind for conflict in reply.ruling.conflicts] == [
        "offer_vs_message", "money_vs_brand", "market_vs_money"
    ]
    # O replica pe membru: Regina pe diagnostic (catre CPO), Researcher-ul catre CFO.
    assert [(r.member, r.replying_to, r.conflict) for r in reply.rebuttals] == [
        ("strategist", "cpo", "offer_vs_message"),
        ("researcher", "cfo", "market_vs_money"),
    ]
    strategist, researcher = reply.rebuttals
    assert strategist.rebuttal.startswith("Eu am căutat problema în mesaj, CPO-ul o vede în ofertă")
    assert strategist.reopen_when == (
        "o reclamă care îi vorbește lui «Ocupatul pragmatic» coboară sub ținta de CPA"
    )
    assert researcher.rebuttal.startswith("Fereastră de oportunitate: cererea urcă")
    assert "Fereastra o folosim prin mesaj, nu prin buget" in researcher.rebuttal
    assert {r.source for r in reply.rebuttals} == {"template"}
    assert f"Se rediscută când {TARGET_REACHED}." in reply.reply


def test_each_member_answers_once_on_its_most_important_dispute() -> None:
    council = QueenCouncil(
        _Static(LOSING),
        technical=_StaticTechnical(_technical(BROKEN_TAG, evidence=GA4_DOWN)),
        clock=lambda: NOW,
    )

    reply = council.evaluate_client_query("Cum ar trebui să arate textele?", _directive())

    kinds = [(conflict.kind, conflict.challenger) for conflict in reply.ruling.conflicts]
    assert kinds == [("veto", "strategist"), ("money_vs_brand", "strategist")]
    [rebuttal] = reply.rebuttals
    assert (rebuttal.member, rebuttal.replying_to, rebuttal.conflict) == (
        "strategist", "technician", "veto"
    )
    assert rebuttal.rebuttal.endswith(
        "Reiau propunerea când testul E2E confirmă că tracking-ul trimite din nou conversiile."
    )


# --- runda a doua, in sinteza ----------------------------------------------------------------


def test_the_loser_answers_the_winner_and_the_chair_hears_it() -> None:
    voice = _CouncilVoice()

    reply = _council(LOSING, voice).evaluate_client_query("Merită să cresc bugetul?", _directive())

    [rebuttal] = reply.rebuttals
    assert (rebuttal.member, rebuttal.replying_to) == ("strategist", "cfo")
    # Replica vine din regula care a transat disputa, fara LLM: modelul scrie doar sinteza.
    assert (rebuttal.source, rebuttal.model) == ("template", None)
    assert rebuttal.rebuttal == reply.ruling.conflicts[0].rebuttal
    assert voice.roles == ["chair"]
    chair = voice.prompt("chair")
    assert (
        "RUNDA DE REPLICI:\n- Regina · strategia de brand, către CFO · rentabilitate: "
        f"{rebuttal.rebuttal}"
    ) in chair
    assert f"Se rediscută când {TARGET_REACHED}." in chair
