"""Profilul cognitiv al cumparatorului: Kahneman, bariera de conversie, ELM.

Clasificarile sunt deterministe si isi arata dovada in cifre. Se verifica
pragurile, cazurile fara date (nu se ghiceste), integrarea in directiva, in
consiliu si in brief-ul de rescriere - si ca limbajul psihologic trece de
garda de cifre doar cu etichetele din fapte.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ppc_agent_server.jobs.brand_alignment import to_rewrite_proposal
from ppc_agent_server.services.cognitive import (
    ad_demand,
    ad_fit_note,
    cognitive_profile,
    conversion_barrier,
    decision_mode,
)
from ppc_agent_server.services.council import (
    CHAIR_SYSTEM_PROMPT,
    build_chair_prompt,
    build_financial_snapshot,
    cfo_position,
    check_council_text,
    classify_question,
    member_opinion,
    rule_on_question,
    strategist_position,
)
from ppc_agent_server.services.queen_agent import build_directive, cmo_facts
from tests_server.test_queen_agent import NOW, _signals
from tests_server.test_queen_council import (
    THIN_DIRECTIVE_SIGNALS,
    _council,
    _CouncilVoice,
    _finances,
)

TECHNICAL_HEADLINE = "Schimb ulei ATF cutie automata"


@dataclass(frozen=True)
class _Profile:
    key: str
    share: float
    paid_clicks: int = 0
    conversions: float = 0.0
    name: str = ""


def _car_service() -> list[_Profile]:
    """Profilurile service-ului auto (aceleasi cifre ca directiva din test_queen_agent)."""
    return [
        _Profile("convenience", 0.604, 60, 14.0, "Ocupatul pragmatic"),
        _Profile("price", 0.1866, 45, 3.0, "Vânătorul de preț"),
        _Profile("research", 0.1135, 35, 0.0, "Cercetătorul"),
        _Profile("trust", 0.0959, 18, 2.0, "Scepticul care vrea garanții"),
    ]


# --- 1. modul de decizie (Kahneman) ---------------------------------------------


@pytest.mark.parametrize(
    ("shares", "expected"),
    [
        ({"convenience": 0.6, "price": 0.2, "research": 0.2}, "system_1"),
        ({"research": 0.5, "trust": 0.2, "price": 0.3}, "system_2"),
        ({"research": 0.3, "trust": 0.2, "urgency": 0.5}, "mixed"),
        ({"urgency": 1.0}, "system_1"),
    ],
)
def test_decision_mode_follows_the_share_of_deliberative_profiles(
    shares: dict[str, float], expected: str
) -> None:
    profiles = [_Profile(key, share, name=key) for key, share in shares.items()]
    assert decision_mode(profiles).system == expected


def test_decision_mode_shows_its_evidence_and_what_the_ad_needs() -> None:
    mode = decision_mode(_car_service())

    assert mode.system == "system_1"
    assert mode.deliberative_share == pytest.approx(0.2094, abs=1e-4)
    assert mode.evidence == (
        "Din publicul care contează, 79% decide repede («Ocupatul pragmatic», «Vânătorul de "
        "preț») și 21% cântărește («Cercetătorul», «Scepticul care vrea garanții»)."
    )
    assert mode.needs == [
        "dovada vizuală a rezultatului",
        "prețul spus direct",
        "un singur îndemn la acțiune",
    ]


# --- 2. bariera de conversie ------------------------------------------------------


def test_price_hunters_who_click_but_do_not_buy_mean_perceived_value() -> None:
    barrier = conversion_barrier(_car_service())

    assert barrier.kind == "perceived_value"
    assert barrier.evidence.startswith(
        "«Vânătorul de preț» aduce 45 de click-uri plătite și 3 conversii (6,7%), sub media "
        "contului de 12%."
    )
    assert barrier.remedy.startswith("Arată întâi ce primește")


@pytest.mark.parametrize(
    ("leaking", "expected"),
    [("trust", "trust"), ("convenience", "friction"), ("urgency", "friction")],
)
def test_the_leaking_profile_names_the_barrier(leaking: str, expected: str) -> None:
    profiles = [
        _Profile("price", 0.4, 100, 20.0, "Preț"),
        _Profile(leaking, 0.4, 80, 1.0, "Profil"),
    ]
    assert conversion_barrier(profiles).kind == expected


def test_researchers_are_not_a_barrier_they_were_not_buying() -> None:
    profiles = [
        _Profile("convenience", 0.6, 100, 20.0, "Ocupatul"),
        _Profile("research", 0.4, 200, 0.0, "Cercetătorul"),
    ]
    barrier = conversion_barrier(profiles)
    assert barrier.kind == "none"
    assert "Niciun profil de cumpărător nu convertește mult sub media contului" in barrier.evidence


def test_without_any_conversion_the_profile_with_most_clicks_is_the_barrier() -> None:
    profiles = [
        _Profile("trust", 0.3, 25, 0.0, "Scepticul"),
        _Profile("price", 0.7, 40, 0.0, "Vânătorul"),
    ]
    barrier = conversion_barrier(profiles)
    assert barrier.kind == "perceived_value"
    assert "contul nu are încă nicio conversie pe căutările plătite" in barrier.evidence


def test_too_few_paid_clicks_is_unknown_not_a_guess() -> None:
    barrier = conversion_barrier([_Profile("price", 1.0, 12, 0.0, "Vânătorul")])
    assert barrier.kind == "unknown"
    assert barrier.evidence.startswith("Doar 12 click-uri plătite atribuite profilurilor")


# --- 3. ruta de persuasiune si parghia --------------------------------------------


@pytest.mark.parametrize(
    ("shares", "route", "lever"),
    [
        ({"convenience": 1.0}, "peripheral", "aversiunea la pierdere: "),
        ({"research": 1.0}, "central", "eliminarea riscului: "),
        ({"research": 0.5, "price": 0.5}, "dual", "aversiunea la pierdere în titlu"),
    ],
)
def test_the_route_and_lever_follow_the_decision_mode(
    shares: dict[str, float], route: str, lever: str
) -> None:
    profile = cognitive_profile([_Profile(key, share, name=key) for key, share in shares.items()])
    assert profile.persuasion_route.route == route
    assert profile.lever.startswith(lever)


def test_the_summary_reads_like_a_consultant() -> None:
    assert cognitive_profile(_car_service()).summary == (
        "Publicul tău decide repede, pe intuiție (Sistemul 1). Îl oprește valoarea percepută: "
        "vede prețul înainte să vadă ce primește. Mesajul merge pe ruta periferică: imagine, "
        "brand, recenzii. Pârghia pentru texte e aversiunea la pierdere (ce pierde omul dacă "
        "mai amână)."
    )


# --- reclamele: ce efort cer --------------------------------------------------------


def test_an_ad_asks_for_system_2_when_it_is_technical_or_long() -> None:
    assert ad_demand("Ulei ATF Dexron VI", technical=True)[0] == "system_2"
    assert ad_demand(" ".join(["cuvânt"] * 31), technical=False) == (
        "system_2",
        "31 de cuvinte de citit înainte de ofertă",
    )
    assert ad_demand("Programare online în 2 minute", technical=False) == ("system_1", "")


def test_a_mismatch_is_explained_both_ways_and_mixed_audiences_accept_both() -> None:
    fast = decision_mode([_Profile("convenience", 1.0, name="c")])
    slow = decision_mode([_Profile("research", 1.0, name="r")])
    mixed = decision_mode([_Profile("research", 0.5, name="r"), _Profile("price", 0.5, name="p")])

    note = ad_fit_note(fast, "X", "system_2", "termeni tehnici")
    assert note == (
        "Publicul tău decide repede, pe intuiție (Sistemul 1). Reclama «X» îl pune să "
        "gândească (Sistemul 2): termeni tehnici. Pierdem atenția."
    )
    assert "e prea sumară pentru el" in (ad_fit_note(slow, "X", "system_1", "") or "")
    assert ad_fit_note(mixed, "X", "system_2", "text lung") is None
    assert ad_fit_note(fast, "X", "system_1", "") is None


# --- in directiva ------------------------------------------------------------------


def test_the_directive_carries_the_cognitive_profile() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    profile = directive.cognitive_profile

    assert directive.version == "1.1"
    assert profile is not None
    assert profile.decision_mode.system == "system_1"
    assert profile.barrier.kind == "perceived_value"
    assert profile.persuasion_route.route == "peripheral"
    assert profile.lever == "aversiunea la pierdere: ce pierde omul dacă mai amână"

    by_headline = {ad.headline: ad for ad in directive.ad_alignment}
    technical = by_headline[TECHNICAL_HEADLINE]
    assert technical.cognitive_demand == "system_2"
    assert technical.cognitive_note is not None
    assert "îl pune să gândească (Sistemul 2): termeni tehnici" in technical.cognitive_note
    convenience = by_headline["Programare online în 2 minute | Gata în aceeași zi"]
    assert (convenience.cognitive_demand, convenience.cognitive_note) == ("system_1", None)


def test_without_an_ideal_client_there_is_no_psychology_to_invent() -> None:
    directive = build_directive(42, _signals(**THIN_DIRECTIVE_SIGNALS), generated_at=NOW)
    assert directive.cognitive_profile is None
    assert all(ad.cognitive_note is None for ad in directive.ad_alignment)


def test_the_llm_facts_carry_the_psychology_and_the_kahneman_legend() -> None:
    facts = cmo_facts(build_directive(42, _signals(), generated_at=NOW))

    assert "Psihologia cumpărătorului (calculată determinist): Publicul tău decide repede" in facts
    assert "«Vânătorul de preț» aduce 45 de click-uri plătite și 3 conversii (6,7%)" in facts
    assert "Sistemul 1 = decizie rapidă, pe intuiție; Sistemul 2 = decizie cântărită" in facts
    assert "îl pune să gândească (Sistemul 2)" in facts
    assert "rezon" not in facts


def test_the_rewrite_brief_tells_the_copywriter_why() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    [ad] = directive.misaligned_ads

    psychology = to_rewrite_proposal(42, ad, directive).after["psychology"]

    assert psychology["decision_mode"] == "system_1"
    assert psychology["conversion_barrier"] == "perceived_value"
    assert psychology["persuasion_route"] == "peripheral"
    assert psychology["persuasion_lever"].startswith("aversiunea la pierdere")
    assert psychology["cognitive_note"] == ad.cognitive_note


# --- in consiliu ---------------------------------------------------------------------


def test_the_council_reply_explains_the_psychology_like_a_consultant() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    reply = _council().evaluate_client_query("Ce facem cu reclama de pe Meta?", directive)

    assert reply.psychology == directive.cognitive_profile
    assert (
        "Publicul tău decide repede, pe intuiție (Sistemul 1). Reclama «Schimb ulei ATF cutie "
        "automata» îl pune să gândească (Sistemul 2)"
    ) in reply.reply
    assert "Pierdem atenția." in reply.reply
    assert reply.reply.startswith(
        "Textele trebuie să vorbească lui «Ocupatul pragmatic», despre timp salvat și zero "
        "bătăi de cap. Publicul tău decide repede"
    )
    assert "Tonul e simplu și liniștitor" in reply.reply
    assert "Propun rescrierea cu accent pe aversiunea la pierdere." in reply.reply
    assert "vede prețul înainte să vadă ce primește" in reply.reply
    assert reply.reply.endswith("Nimic nu se aplică fără aprobarea ta.")


def test_the_brand_position_and_the_queen_carry_the_psychology() -> None:
    assert "motivația psihologică din poziția ta de brand" in CHAIR_SYSTEM_PROMPT

    voice = _CouncilVoice()
    directive = build_directive(42, _signals(), generated_at=NOW)
    reply = _council(voice=voice).evaluate_client_query(
        "Ce facem cu reclama de pe Meta?", directive
    )
    assert directive.cognitive_profile is not None
    summary = directive.cognitive_profile.summary
    strategist, cfo = reply.opinions[0], reply.opinions[1]
    assert summary in strategist.opinion
    assert summary not in cfo.opinion
    assert summary in voice.prompt("chair")


def _chair_facts(question: str) -> str:
    directive = build_directive(42, _signals(), generated_at=NOW)
    finances = build_financial_snapshot(_finances())
    ruling = rule_on_question(
        classify_question(question, active_platforms={"meta", "google"}), directive, finances
    )
    opinions = [
        member_opinion("strategist", strategist_position(directive), has_data=True),
        member_opinion("cfo", cfo_position(finances), has_data=True),
    ]
    _, user = build_chair_prompt(question, opinions, ruling=ruling)
    return user


def test_psychological_language_passes_the_guard_only_with_real_numbers() -> None:
    facts = _chair_facts("Ce facem cu reclama de pe Meta?")
    target = (
        "Publicul tău decide impulsiv (Sistemul 1). Reclama actuală îi forțează să gândească "
        "prea mult (Sistemul 2). Pierdem atenția. Propun rescrierea cu focus pe aversiunea la "
        "pierdere."
    )
    assert check_council_text(target, facts=facts) is None

    invented = target + " Studiile arată că 95% din deciziile de cumpărare sunt inconștiente."
    problem = check_council_text(invented, facts=facts)
    assert problem is not None and "(95)" in problem
