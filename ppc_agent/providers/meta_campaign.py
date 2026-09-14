"""Traduce ``CampaignObjective`` in formatul exact al Meta Marketing API (ODAX).

Functie pura, fara niciun apel de retea - construieste DOAR payload-ul, nu-l
trimite (creare de campanie reala ramane in afara scopului, ca toti clientii
``live`` din :mod:`ppc_agent.providers.live`, care cer credentiale reale si
inca nu sunt implementati).

``objective`` e un camp de CAMPANIE in API-ul real (ODAX: ``OUTCOME_SALES``,
``OUTCOME_LEADS``, ...), dar ``optimization_goal``/``promoted_object`` sunt
campuri de AD SET, nu de campanie - Meta le separa asa, de-asta payload-ul de
mai jos are ambele niveluri, nu un singur dict plat.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from ppc_agent.campaign_objective import CampaignObjective

MetaObjective = Literal["OUTCOME_SALES", "OUTCOME_LEADS"]
MetaOptimizationGoal = Literal["OFFSITE_CONVERSIONS"]
MetaCustomEventType = Literal["PURCHASE", "LEAD"]


class MetaPromotedObject(TypedDict):
    custom_event_type: MetaCustomEventType


class MetaAdSetOptimization(TypedDict):
    optimization_goal: MetaOptimizationGoal
    promoted_object: MetaPromotedObject


class MetaCampaignPayload(TypedDict):
    objective: MetaObjective
    ad_set: MetaAdSetOptimization


def build_meta_campaign_payload(objective: CampaignObjective) -> MetaCampaignPayload:
    """Payload-ul Meta (campanie + ad set) pentru un ``CampaignObjective`` dat.

    Ambele obiective optimizeaza pe conversii urmarite prin pixel/CAPI
    (``OFFSITE_CONVERSIONS``) - diferenta e evenimentul tinta:
    ``PURCHASE`` pentru SALES, ``LEAD`` pentru LEAD_GEN (ambele nume de
    evenimente standard Meta Pixel/CAPI).

    Args:
        objective: Obiectivul clientului (citit din ``ClientAccount.objective``,
            niciodata ghicit).

    Returns:
        ``objective`` la nivel de campanie plus ``optimization_goal`` si
        ``promoted_object`` la nivel de ad set.
    """
    event_type: MetaCustomEventType
    meta_objective: MetaObjective
    if objective == CampaignObjective.SALES:
        meta_objective, event_type = "OUTCOME_SALES", "PURCHASE"
    else:
        meta_objective, event_type = "OUTCOME_LEADS", "LEAD"

    return {
        "objective": meta_objective,
        "ad_set": {
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "promoted_object": {"custom_event_type": event_type},
        },
    }
