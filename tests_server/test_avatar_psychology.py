"""Psihologia consumatorului: avatarul JTBD, propensitatea CMO-ului, garda anti-frica, CPO-ul.

Pur, fara DB: acelasi service de cutii automate ca in ``test_queen_agent``, plus ce a spus
clientul in interviu (clientul ideal, pachetele, garantia).
"""

from __future__ import annotations

import pytest

import ppc_agent_server.services.queen_agent as qa
from ppc_agent_server.jobs.brand_alignment import to_rewrite_proposal
from ppc_agent_server.services.avatar_builder import (
    PROFILE_KEYS,
    CustomerAvatar,
    OfferFacts,
    avatar_from_answers,
    profile_missing,
)
from ppc_agent_server.services.council import check_council_text, strategist_position
from ppc_agent_server.services.cpo import evaluate_offer
from ppc_agent_server.services.propensity import (
    design_experiment,
    fear_manipulation_risk,
    score_propensity,
)
from ppc_agent_server.services.queen_agent import (
    AvatarProfile,
    build_directive,
    check_cmo_message,
    cmo_facts,
    template_cmo_message,
)
from tests_server.test_queen_agent import NOW, _signals

AVATAR = CustomerAvatar(
    customer_situation="I s-a stricat cutia automată înainte de concediu",
    functional_job="mașina reparată până vineri",
    desired_progress="să plece liniștit la drum",
    emotional_job="liniștit",
    anxieties=["prețul", "că nu știe dacă lucrarea iese bine"],
    switching_cost="merge la service-ul de lângă bloc",
)
#: 5 pachete si nicio garantie: choice overload si riscul neacoperit.
CROWDED = OfferFacts(options=5, risk_reversal="")


def test_the_customer_avatar_schema_has_the_seven_jtbd_fields() -> None:
    schema = CustomerAvatar.model_json_schema()

    assert schema["title"] == "CustomerAvatar"
    assert list(schema["properties"]) == [
        "customer_situation",
        "desired_progress",
        "functional_job",
        "emotional_job",
        "social_job",
        "anxieties",
        "switching_cost",
    ]
    assert schema["properties"]["anxieties"]["type"] == "array"
    assert "required" not in schema  # "nu stiu" e un raspuns: niciun camp nu e obligatoriu


def test_a_dont_know_is_an_answer_and_nothing_is_invented() -> None:
    assert profile_missing(None) == "customer_situation"
    assert profile_missing({"customer_situation": "x"}) == "functional_job"
    all_unknown = dict.fromkeys(PROFILE_KEYS)
    assert profile_missing(all_unknown) is None
    assert avatar_from_answers(all_unknown) is None
    assert avatar_from_answers({"emotional_job": "liniștit", "anxieties": []}) == CustomerAvatar(
        emotional_job="liniștit"
    )


def test_propensity_names_the_dominant_barrier_from_the_clients_own_words() -> None:
    """Pretul (-2 valoare), "iese bine" (+2 risc), schimbarea (+1 risc), 5 pachete (+2
    frictiune)."""
    score = score_propensity(avatar=AVATAR, offer=CROWDED, measured_barrier=None, alignment=[])

    assert (score.relevance, score.value, score.trust, score.risk, score.friction) == (
        5, 3, 5, 8, 7,
    )
    assert score.p_action == (5 + 3 + 5) - (8 + 7)
    assert score.dominant_barrier == "perceived_risk"
    assert "Riscul +2: clientul se teme de rezultat («că nu știe dacă lucrarea iese bine»)." in (
        score.evidence
    )


def test_the_measured_barrier_and_the_ads_alignment_move_the_factors() -> None:
    score = score_propensity(
        avatar=None, offer=None, measured_barrier="trust", alignment=[0.9, 0.7]
    )
    assert (score.relevance, score.trust) == (8, 2)
    assert score.dominant_barrier == "lack_of_trust"


def test_without_any_evidence_there_is_no_barrier_and_no_experiment() -> None:
    blank = score_propensity(avatar=None, offer=None, measured_barrier=None, alignment=[])
    assert blank.p_action == 5 and blank.dominant_barrier is None
    assert design_experiment(blank, None) is None


def test_the_experiment_is_falsifiable() -> None:
    score = score_propensity(avatar=AVATAR, offer=CROWDED, measured_barrier=None, alignment=[])
    experiment = design_experiment(score, AVATAR)

    assert experiment is not None
    assert experiment.barrier == "perceived_risk"
    assert experiment.hypothesis.startswith("Dacă spunem în titlu inversarea riscului")
    assert "crește cu cel puțin 15% față de reclama actuală" in experiment.hypothesis
    assert experiment.control.startswith("Reclama actuală, neschimbată")
    assert experiment.min_sample == "cel puțin 100 de click-uri pe fiecare variantă și 14 zile"
    assert experiment.falsified_if.startswith("varianta nu bate controlul cu 15% după eșantion")


def test_the_jtbd_avatar_reaches_the_cmo_even_without_account_data() -> None:
    directive = build_directive(
        1, _signals(searches=[], ads=[], customer_avatar=AVATAR, offer=CROWDED), generated_at=NOW
    )

    assert directive.status == "insufficient_data"
    assert directive.customer_avatar == AVATAR
    assert directive.experiment is not None
    assert "Bariera dominantă e riscul perceput." in template_cmo_message(directive)
    assert "Bariera dominantă e riscul perceput." in strategist_position(directive)


def test_every_agent_reads_the_avatar_from_the_directive() -> None:
    directive = build_directive(
        1, _signals(customer_avatar=AVATAR, offer=CROWDED), generated_at=NOW
    )
    facts = cmo_facts(directive)

    assert (
        "Clientul ideal, în cuvintele afacerii (Jobs to Be Done) - situația: «I s-a stricat "
        "cutia automată înainte de concediu»"
    ) in facts
    assert "Propensitatea de cumpărare (calculată determinist" in facts
    # Contul arata deja ca pretul opreste (bariera masurata) - plus ce spune clientul.
    assert directive.experiment is not None
    assert directive.experiment.barrier == "price_uncertainty"
    assert "Experimentul: Dacă spunem prețul" in strategist_position(directive)
    brief = to_rewrite_proposal(1, directive.misaligned_ads[0], directive).after
    assert brief["customer_avatar"]["functional_job"] == "mașina reparată până vineri"
    assert brief["experiment"]["barrier"] == "price_uncertainty"
    assert "guardrails" not in brief  # un service auto nu e un domeniu sensibil


def test_the_cpo_caps_the_offer_at_three_packages_and_reverses_the_risk() -> None:
    directive = build_directive(
        1, _signals(customer_avatar=AVATAR, offer=CROWDED), generated_at=NOW
    )
    product = evaluate_offer(directive, unprofitable=False, generated_at=NOW)

    assert product.choice_architecture == (
        "Arhitectura alegerii: 5 pachete sunt prea multe: peste 3, clientul amână alegerea. "
        "Cel mult 3, clare, cu unul recomandat. Lipsește inversarea riscului: propun prețul "
        "fix, scris dinainte, fără costuri ascunse."
    )
    assert [move.kind for move in product.moves[:2]] == ["risk_reversal", "simplify"]
    # Povestea ofertei, cu cuvintele clientului.
    assert product.story.startswith(
        "Problema: «I s-a stricat cutia automată înainte de concediu». Promisiunea: «să plece "
        "liniștit la drum»."
    )


def test_without_search_data_the_cpo_still_judges_the_choice() -> None:
    offer = OfferFacts(options=2, risk_reversal="garanție 12 luni")
    directive = build_directive(1, _signals(searches=[], ads=[], offer=offer), generated_at=NOW)
    product = evaluate_offer(directive, unprofitable=False, generated_at=NOW)

    assert product.status == "unknown" and product.moves == []
    assert product.choice_architecture == (
        "Arhitectura alegerii: 2 pachete: alegerea e ușoară. Garanția există («garanție 12 "
        "luni»): pune-o în prim-plan."
    )


# --- garda fear_manipulation_risk ------------------------------------------------------


def test_a_health_business_gets_no_fear_trigger_and_no_loss_aversion() -> None:
    directive = build_directive(1, _signals(brand="Clinica Dentară Zâmbet"), generated_at=NOW)

    assert directive.sensitive_domain == "health"
    assert directive.cognitive_profile is not None
    assert directive.cognitive_profile.lever.startswith("eliminarea riscului")
    assert directive.copywriting_angle is not None
    assert directive.copywriting_angle.avoid[-1] == (
        "frica și tonul alarmist: domeniu sensibil (sănătate), regula fear_manipulation_risk"
    )
    brief = to_rewrite_proposal(1, directive.misaligned_ads[0], directive).after
    assert brief["guardrails"]["fear_manipulation_risk"].startswith(
        "blocat: domeniu sensibil (sănătate)"
    )


def test_fear_triggers_never_reach_the_copywriter_in_a_sensitive_domain() -> None:
    urgent = AvatarProfile(
        key="urgency", name="Grăbitul", share=0.6, dominant=True, pains=[], desires=[],
        objections=[], decision_style="", sample_queries=[],
    )
    assert qa._angle(urgent, []).emotion_trigger == "urgenta"
    assert qa._angle(urgent, [], "finance").emotion_trigger == "beneficiu"


@pytest.mark.parametrize(
    "text",
    [
        "Riști să pierzi tot dacă mai aștepți!",
        "Mâine poate fi prea târziu pentru dinții tăi.",
        "Fără tratament apar complicații grave.",
    ],
)
def test_alarmist_text_is_caught(text: str) -> None:
    assert fear_manipulation_risk(text)


def test_calm_text_passes() -> None:
    assert fear_manipulation_risk("Programare azi, garanție scrisă, fără costuri ascunse.") == []


def test_the_model_cannot_write_alarmist_text_in_a_sensitive_domain() -> None:
    alarm = "Riști să pierzi tot dacă mai aștepți."
    problem = check_cmo_message(alarm, facts="", sensitive=True)
    assert problem is not None and problem.startswith("Mesajul modelului avea ton alarmist")
    assert check_cmo_message(alarm, facts="") is None  # in afara domeniilor sensibile
    assert check_council_text(alarm, facts="", sensitive=True) == (
        "avea ton alarmist într-un domeniu sensibil («risti»)"
    )
