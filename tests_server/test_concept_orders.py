"""Sablonul de concept al CMO-ului, de la ipoteza la copywriter, CCO si ordinele PPC."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.providers.meta_campaign import MetaAdCreative, MetaLaunchSpec
from ppc_agent_server.jobs.brand_alignment import to_rewrite_proposal
from ppc_agent_server.models import ClientAccount
from ppc_agent_server.routers.campaigns import get_creative_review
from ppc_agent_server.services.avatar_builder import CustomerAvatar, OfferFacts
from ppc_agent_server.services.campaign_orders import (
    strategy_orders,
    with_creative,
)
from ppc_agent_server.services.creative_context import CreativeEvaluationContext
from ppc_agent_server.services.propensity import (
    Experiment,
    PropensityScore,
    choose_concept,
    design_experiment,
    experiment_line,
)
from ppc_agent_server.services.queen_agent import build_directive
from tests_server.test_avatar_psychology import AVATAR, CROWDED, NOW, _signals
from tests_server.test_campaign_launch import _cco, _request, launcher  # noqa: F401

JOB = CustomerAvatar(functional_job="mașina reparată până vineri")


def _score(barrier: str) -> PropensityScore:
    return PropensityScore(
        relevance=5,
        value=5,
        trust=5,
        risk=5,
        friction=5,
        p_action=5,
        dominant_barrier=barrier,
        evidence=[],  # type: ignore[arg-type]
    )


# --- CMO: sablonul pe bariera ------------------------------------------------------


@pytest.mark.parametrize(
    ("barrier", "avatar", "offer", "expected"),
    [
        ("lack_of_trust", None, None, "founder_story"),
        ("friction", None, OfferFacts(options=5), "us_vs_them"),
        ("friction", None, OfferFacts(options=2), "product_demo"),
        ("price_uncertainty", None, None, "us_vs_them"),
        ("perceived_risk", JOB, None, "before_after"),
        ("low_relevance", JOB, None, "before_after"),
        ("perceived_risk", None, None, "testimonial"),
        ("low_relevance", None, None, "testimonial"),
    ],
)
def test_cmo_alege_sablonul_dupa_bariera(
    barrier: str, avatar: CustomerAvatar | None, offer: OfferFacts | None, expected: str
) -> None:
    concept, reason = choose_concept(barrier, avatar, offer)  # type: ignore[arg-type]
    assert concept == expected
    assert reason


def test_ipoteza_include_sablonul_si_motivul() -> None:
    experiment = design_experiment(_score("friction"), None, OfferFacts(options=6))

    assert experiment is not None
    assert experiment.concept_template == "us_vs_them"
    assert "choice overload" in experiment.concept_reason
    assert "Conceptul reclamei: Noi vs. ei." in experiment_line(experiment)


def test_o_ipoteza_salvata_inainte_de_sabloane_primeste_sablonul_barierei() -> None:
    saved = {
        "barrier": "lack_of_trust",
        "hypothesis": "h",
        "change": "c",
        "control": "c",
        "metric": "m",
        "success_criterion": "s",
        "min_sample": "n",
        "falsified_if": "f",
    }
    assert Experiment.model_validate(saved).concept_template == "founder_story"


def test_directiva_reginei_si_brief_ul_copywriterului_poarta_conceptul() -> None:
    directive = build_directive(
        1, _signals(customer_avatar=AVATAR, offer=CROWDED), generated_at=NOW
    )
    assert directive.experiment is not None
    concept = directive.experiment.concept_template

    brief = to_rewrite_proposal(1, directive.misaligned_ads[0], directive).after
    assert brief["experiment"]["concept_template"] == concept
    assert brief["concept"]["template"] == concept
    assert brief["concept"]["copy_beats"]


# --- ordinele catre PPC ----------------------------------------------------------


def _account(pixel: str | None = "1234567890") -> ClientAccount:
    return ClientAccount(
        tenant_id=1, name="Service", objective=CampaignObjective.LEAD_GEN, meta_pixel_id=pixel
    )


def _experiment() -> Experiment:
    experiment = design_experiment(_score("lack_of_trust"), None)
    assert experiment is not None
    return experiment


def _launch_spec(*extra: MetaAdCreative, concept: str = "founder_story") -> MetaLaunchSpec:
    return MetaLaunchSpec(
        campaign_name="Service",
        objective=CampaignObjective.LEAD_GEN,
        daily_budget=Decimal("50"),
        pixel_id="1234567890",
        custom_event_type="LEAD",
        page_id="9876543210",
        target_url="https://exemplu.ro/p",
        headline="Titlu",
        primary_text="Text",
        image_url="https://cdn.exemplu.ro/a.jpg",
        country="RO",
        call_to_action="LEARN_MORE",
        concept_template=concept,
        extra_ads=extra,
    )


def test_ordinele_de_strategie_vin_din_cont_si_din_ipoteza() -> None:
    orders = strategy_orders(_account(), _experiment(), max_ads=3)

    assert orders.optimization_goal == "OFFSITE_CONVERSIONS"
    assert orders.optimization_event == "LEAD"
    assert orders.objective == "OUTCOME_LEADS"
    assert (orders.pixel_id, orders.capi_ready) == ("1234567890", True)
    assert orders.concept_template == "founder_story"
    assert orders.issued_by == ["cmo"]
    assert orders.deviations == []


def test_fara_pixel_in_cont_ordinele_noteaza_ca_lipseste_capi() -> None:
    orders = strategy_orders(_account(pixel=None), None, max_ads=None)
    assert not orders.capi_ready
    assert "CAPI" in orders.deviations[0]


def test_cco_completeaza_ordinele_pe_fiecare_reclama() -> None:
    video = MetaAdCreative(
        "Alt",
        "Alt text",
        "https://cdn.exemplu.ro/b.jpg",
        video_url="https://cdn.exemplu.ro/b.mp4",
        concept_template="testimonial",
    )
    orders = with_creative(
        strategy_orders(_account(), _experiment(), max_ads=3),
        _launch_spec(video),
        [
            {"decision": "ELIGIBLE_FOR_TEST", "follows_concept": True},
            {"decision": "ELIGIBLE_FOR_TEST", "follows_concept": False, "priority_fixes": ["x"]},
        ],
    )

    first, second = orders.ads
    assert (first.role, first.format, first.status) == ("cmo_variant", "image", "cleared")
    assert (second.role, second.format, second.status) == ("diversity", "video", "fix_first")
    assert any("reclama 2 nu respecta conceptul" in d for d in orders.deviations)
    assert orders.issued_by == ["cmo", "cco"]


def test_abaterea_cand_nicio_reclama_nu_foloseste_conceptul_cmo() -> None:
    orders = with_creative(
        strategy_orders(_account(), _experiment(), max_ads=3),
        _launch_spec(concept="product_demo"),
        [{"decision": "ELIGIBLE_FOR_TEST"}],
    )
    assert any("Povestea fondatorului" in d for d in orders.deviations)


# --- propose_launch aplica ordinele -------------------------------------------------


def _with_hypothesis(session: Session, account_id: int) -> None:
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.cmo_hypothesis = _experiment().model_dump(mode="json")
    session.add(account)
    session.commit()


def _recording_review(client: TestClient) -> list[tuple[str, CreativeEvaluationContext]]:
    seen: list[tuple[str, CreativeEvaluationContext]] = []

    def review(media_url: str, context: CreativeEvaluationContext) -> dict[str, Any]:
        seen.append((media_url, context))
        return {**_cco("ELIGIBLE_FOR_TEST"), "follows_concept": True}

    client.app.dependency_overrides[get_creative_review] = lambda: review  # type: ignore[attr-defined]
    return seen


def test_propunerea_poarta_ordinele_si_prima_reclama_primeste_conceptul_cmo(
    launcher: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
) -> None:
    client, headers, account_id = launcher
    _with_hypothesis(session, account_id)
    seen = _recording_review(client)

    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())

    assert response.status_code == 201
    body = response.json()
    assert body["after"]["concept_template"] == "founder_story"
    orders = body["before"]["campaign_orders"]
    assert orders["optimization_event"] == "LEAD"  # contul e pe lead-uri
    assert orders["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert orders["concept_template"] == "founder_story"
    assert orders["issued_by"] == ["cmo", "consiliu", "cco"]
    assert orders["ads"][0]["status"] == "cleared"
    assert "Ordine PPC: optimizare pe LEAD" in body["rationale"]
    assert seen[0][1].cmo_hypothesis is not None
    assert seen[0][1].concept_template == "founder_story"


def test_reclama_de_diversitate_se_judeca_pe_conceptul_ei_fara_ipoteza(
    launcher: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
) -> None:
    client, headers, account_id = launcher
    _with_hypothesis(session, account_id)
    seen = _recording_review(client)
    extra = {
        "headline": "Clientii nostri spun",
        "primary_text": "Andrei din Cluj: cutia reparata in doua zile.",
        "image_url": "https://cdn.exemplu.ro/coperta.jpg",
        "video_url": "https://cdn.exemplu.ro/marturie.mp4",
        "concept_template": "testimonial",
    }

    response = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request(extra_ads=[extra])
    )

    assert response.status_code == 201
    url, context = seen[1]
    assert url == "https://cdn.exemplu.ro/marturie.mp4"  # CCO vede video-ul, nu coperta
    assert context.cmo_hypothesis is None
    assert context.concept_template == "testimonial"
    ads = response.json()["before"]["campaign_orders"]["ads"]
    assert [(ad["format"], ad["role"]) for ad in ads] == [
        ("image", "cmo_variant"),
        ("video", "diversity"),
    ]


def test_alt_eveniment_decat_cel_al_contului_incalca_ordinele(
    launcher: tuple[TestClient, dict[str, str], int],  # noqa: F811
) -> None:
    client, headers, _ = launcher
    response = client.post(
        "/api/v1/campaigns/propose_launch",
        headers=headers,
        json=_request(custom_event_type="CONTACT"),  # trimis prin CAPI, dar nu al contului
    )
    assert response.status_code == 422
    assert "ordinele consiliului" in response.json()["detail"]


def test_un_pixel_diferit_de_cel_cu_capi_incalca_ordinele(
    launcher: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
) -> None:
    client, headers, account_id = launcher
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.meta_pixel_id = "5555555555"
    session.add(account)
    session.commit()

    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())

    assert response.status_code == 422
    assert "CAPI" in response.json()["detail"]
