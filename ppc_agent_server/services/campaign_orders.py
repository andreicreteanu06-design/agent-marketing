"""Ordinele de configurare pentru agentul PPC: ce cer consiliul, CMO-ul si CCO-ul.

Pana aici, agentul PPC construia lansarea doar din cererea clientului, iar ceilalti
agenti isi dadeau avizul la final. Acum ordinele vin INAINTE si se aplica:

    CMO (ipoteza)  --bariera, sablonul de concept-----------\\
    consiliul      --decizia, veto-ul------------------------> CampaignOrders --> PPC
    CCO (verdict)  --pe fiecare reclama: format, concept-----/

1. **Strategia** (:func:`strategy_orders`, inainte de specificatie): obiectivul si
   evenimentul de optimizare din contul clientului (cel trimis prin CAPI), pixelul pe
   care pleaca conversiile, structura (o campanie, un ad set, targetare larga), cate
   reclame hraneste bugetul si sablonul de concept cerut de CMO pentru bariera.
   Agentul PPC (``routers/campaigns._build_spec``) le aplica: un eveniment sau un
   pixel diferit se refuza, iar prima reclama primeste sablonul CMO-ului.
2. **Consiliul** (:func:`with_council`): decizia si veto-ul, dupa deliberare.
3. **CCO** (:func:`with_creative`): pe fiecare reclama - formatul, sablonul dupa care
   a fost judecata, daca il respecta si ce trebuie reparat inainte de bani.

Ordinele se pastreaza in propunere (``before["campaign_orders"]``), ca omul care
aproba sa vada cine a cerut ce si unde lansarea se abate de la ordine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from ppc_agent.creative.concepts import CONCEPTS, ConceptTemplate, concept_label
from ppc_agent.providers.meta_campaign import (
    CONVERSION_OPTIMIZATION_GOAL,
    MetaLaunchSpec,
    build_meta_campaign_payload,
)
from ppc_agent_server.models import ClientAccount
from ppc_agent_server.services.council import CouncilReply
from ppc_agent_server.services.propensity import BARRIER_LABELS, Barrier, Experiment

#: Cheia ordinelor in ``ProposedChange.before``.
ORDERS_KEY = "campaign_orders"
#: Verdictul CCO-ului care opreste o reclama (acelasi ca in ``routers/campaigns``).
_CCO_BLOCKS = "REVISE_BEFORE_TEST"

AdRole = Literal["cmo_variant", "diversity"]
AdStatus = Literal["cleared", "fix_first", "human_review", "not_evaluated"]


class AdOrder(BaseModel):
    """Ce spune CCO-ul despre o reclama a lansarii."""

    position: int = Field(ge=1)
    format: Literal["image", "video"]
    concept_template: ConceptTemplate | None
    #: ``cmo_variant`` = varianta testului CMO-ului; ``diversity`` = Andromeda, alt unghi.
    role: AdRole
    cco_decision: str | None = None
    follows_concept: bool | None = None
    status: AdStatus = "not_evaluated"
    fixes: list[str] = Field(default_factory=list)


class CampaignOrders(BaseModel):
    """Setarile pe care agentul PPC trebuie sa le aplice, cu sursa fiecareia."""

    version: Literal["1"] = "1"
    issued_by: list[str] = Field(default_factory=list)
    # --- CMO: bariera si conceptul ---
    barrier: str | None = None
    concept_template: ConceptTemplate | None = None
    concept_reason: str = ""
    hypothesis: str | None = None
    # --- setarile campaniei ---
    objective: str
    optimization_goal: str = CONVERSION_OPTIMIZATION_GOAL
    optimization_event: str
    #: Pixelul pe care pleaca si conversiile calificate prin CAPI; ``None`` = neconfigurat.
    pixel_id: str | None = None
    capi_ready: bool = False
    bid_strategy: Literal["LOWEST_COST_WITHOUT_CAP"] = "LOWEST_COST_WITHOUT_CAP"
    targeting: str = "larg: doar locatia, plus Advantage+ audience"
    structure: str = "o campanie, un ad set, toate reclamele in el"
    #: Cate reclame hraneste bugetul (``recommend_arm_capacity``); ``None`` = necunoscut.
    max_ads: int | None = None
    # --- consiliul ---
    council_decision: str | None = None
    council_veto: str | None = None
    # --- CCO ---
    ads: list[AdOrder] = Field(default_factory=list)
    #: Unde lansarea se abate de la ordine (omul decide la aprobare).
    deviations: list[str] = Field(default_factory=list)


def strategy_orders(
    account: ClientAccount, hypothesis: Experiment | None, *, max_ads: int | None
) -> CampaignOrders:
    """Ordinele de dinaintea specificatiei: din contul clientului si din ipoteza CMO-ului."""
    payload = build_meta_campaign_payload(account.objective)
    pixel = account.meta_pixel_id or None
    orders = CampaignOrders(
        issued_by=["cmo"] if hypothesis is not None else [],
        objective=payload["objective"],
        optimization_goal=payload["ad_set"]["optimization_goal"],
        optimization_event=payload["ad_set"]["promoted_object"]["custom_event_type"],
        pixel_id=pixel,
        capi_ready=pixel is not None,
        max_ads=max_ads,
    )
    if hypothesis is not None:
        orders.barrier = hypothesis.barrier
        orders.concept_template = hypothesis.concept_template
        orders.concept_reason = hypothesis.concept_reason
        orders.hypothesis = hypothesis.hypothesis
    if pixel is None:
        orders.deviations.append(
            "contul nu are pixelul Meta setat: conversiile calificate nu pleaca prin CAPI, "
            "deci Meta va invata doar din pixelul de pe site"
        )
    return orders


def request_violations(
    orders: CampaignOrders, *, custom_event_type: str | None, pixel_id: str
) -> list[str]:
    """Ce din cererea clientului incalca ordinele (agentul PPC o refuza)."""
    problems = []
    if custom_event_type is not None and custom_event_type != orders.optimization_event:
        problems.append(
            f"campania optimizeaza pe {orders.optimization_event} (evenimentul contului, "
            f"trimis calificat prin CAPI), nu pe {custom_event_type}"
        )
    if orders.pixel_id is not None and pixel_id != orders.pixel_id:
        problems.append(
            f"pixelul {pixel_id} nu e cel pe care trimitem conversiile CAPI ({orders.pixel_id}): "
            "Meta ar optimiza pe un pixel care nu primeste conversiile calificate"
        )
    return problems


def with_council(orders: CampaignOrders, reply: CouncilReply) -> CampaignOrders:
    """Ordinele, cu decizia si veto-ul consiliului."""
    return orders.model_copy(
        update={
            "issued_by": [*orders.issued_by, "consiliu"],
            "council_decision": reply.ruling.decision,
            "council_veto": reply.ruling.veto,
        }
    )


def _status(review: dict[str, Any]) -> AdStatus:
    decision = review.get("decision")
    if decision is None:
        return "not_evaluated"
    if decision == _CCO_BLOCKS or review.get("follows_concept") is False:
        return "fix_first"
    if decision == "HUMAN_REVIEW_REQUIRED":
        return "human_review"
    return "cleared"


def with_creative(
    orders: CampaignOrders, spec: MetaLaunchSpec, reviews: Sequence[dict[str, Any]]
) -> CampaignOrders:
    """Ordinele, cu verdictul CCO-ului pe fiecare reclama si abaterile de la ordine.

    Args:
        reviews: Verdictele CCO, in ordinea ``spec.ads`` (o evaluare indisponibila
            are ``unavailable`` in loc de ``decision``).
    """
    ads: list[AdOrder] = []
    for position, (ad, review) in enumerate(zip(spec.ads, reviews, strict=True), start=1):
        concept = ad.concept_template or None
        ads.append(
            AdOrder(
                position=position,
                format=ad.format,
                concept_template=cast("ConceptTemplate | None", concept),
                role="cmo_variant" if position == 1 and orders.concept_template else "diversity",
                cco_decision=review.get("decision"),
                follows_concept=review.get("follows_concept"),
                status=_status(review),
                fixes=list(review.get("priority_fixes", []))[:3],
            )
        )
    deviations = list(orders.deviations)
    wanted = orders.concept_template
    if wanted is not None and all(order.concept_template != wanted for order in ads):
        barrier = cast("Barrier | None", orders.barrier)
        reason = f", ales pentru {BARRIER_LABELS[barrier]}" if barrier in BARRIER_LABELS else ""
        deviations.append(
            f"nicio reclama nu foloseste conceptul cerut de CMO ({CONCEPTS[wanted].label}{reason})"
        )
    for order in ads:
        if order.follows_concept is False:
            deviations.append(
                f"reclama {order.position} nu respecta conceptul "
                f"«{concept_label(order.concept_template)}» (CCO)"
            )
    if orders.max_ads is not None and len(ads) > orders.max_ads:
        deviations.append(f"{len(ads)} reclame, dar bugetul hraneste cel mult {orders.max_ads}")
    return orders.model_copy(
        update={
            "issued_by": [*orders.issued_by, "cco"],
            "ads": ads,
            "deviations": deviations,
        }
    )


def orders_summary(orders: CampaignOrders) -> str:
    """Ordinele intr-o fraza, pentru motivul propunerii."""
    parts = [
        f"Ordine PPC: optimizare pe {orders.optimization_event} ({orders.optimization_goal})"
        + (" prin pixel + CAPI" if orders.capi_ready else ", fara CAPI")
    ]
    if orders.concept_template is not None:
        parts.append(f"concept cerut de CMO: {CONCEPTS[orders.concept_template].label}")
    if orders.ads:
        formats = ", ".join(
            f"{ad.position}: {ad.format}"
            + (f" / {concept_label(ad.concept_template)}" if ad.concept_template else "")
            for ad in orders.ads
        )
        parts.append(f"reclame ({formats})")
    if orders.deviations:
        parts.append(f"abateri: {len(orders.deviations)}")
    return "; ".join(parts) + "."
