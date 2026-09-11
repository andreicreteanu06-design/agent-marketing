"""Teste pentru build_proposed_changes() - in special denumirea resursei per platforma.

Nu exista alt fisier care sa testeze direct aceasta functie (doar indirect, prin
CLI, in test_propose_cli.py) - acestea sunt testele unitare dedicate.
"""

from __future__ import annotations

from decimal import Decimal

from ppc_agent.alignment.models import LiquidityPlan
from ppc_agent.decision.models import BudgetAllocation, BudgetPlan
from ppc_agent.guardrails.pipeline import build_proposed_changes
from ppc_agent.ingestion.models import NegativeKeywordSet

_EMPTY_NEGATIVES = NegativeKeywordSet()
_EMPTY_LIQUIDITY = LiquidityPlan(target_weekly_conversions=50)


def _plan(*allocations: BudgetAllocation) -> BudgetPlan:
    total = sum((a.daily_budget for a in allocations), Decimal("0"))
    return BudgetPlan(
        daily_budget=total,
        total_allocated=total,
        n_samples=100,
        seed=1,
        allocations=list(allocations),
    )


def test_google_ads_allocation_keeps_campaign_resource_naming() -> None:
    plan = _plan(
        BudgetAllocation(
            arm_id="c_brand",
            name="Search - Brand",
            platform="google_ads",
            win_probability=0.8,
            final_share=1.0,
            daily_budget=Decimal("30.00"),
        )
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    assert len(changes) == 1
    assert changes[0].resource == "campaign/c_brand"
    assert changes[0].resource_type == "campaign"


def test_tiktok_ads_allocation_uses_ad_group_resource_naming() -> None:
    plan = _plan(
        BudgetAllocation(
            arm_id="tt_spark",
            name="Spark Ads - UGC",
            platform="tiktok_ads",
            win_probability=0.6,
            final_share=1.0,
            daily_budget=Decimal("20.00"),
        )
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    assert len(changes) == 1
    assert changes[0].resource == "tiktok_ad_group/tt_spark"
    assert changes[0].resource_type == "ad_group"


def test_default_platform_omitted_still_resolves_to_google_ads() -> None:
    """BudgetAllocation fara platform explicit (implicit) se comporta ca inainte."""
    plan = _plan(
        BudgetAllocation(
            arm_id="c_generic",
            name="Search - Generic",
            win_probability=0.5,
            final_share=1.0,
            daily_budget=Decimal("10.00"),
        )
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    assert changes[0].resource == "campaign/c_generic"


def test_mixed_platform_allocations_each_get_correct_resource_type() -> None:
    plan = _plan(
        BudgetAllocation(
            arm_id="c_brand",
            name="Search - Brand",
            platform="google_ads",
            win_probability=0.7,
            final_share=0.6,
            daily_budget=Decimal("30.00"),
        ),
        BudgetAllocation(
            arm_id="tt_infeed",
            name="In-Feed - Conversii",
            platform="tiktok_ads",
            win_probability=0.3,
            final_share=0.4,
            daily_budget=Decimal("20.00"),
        ),
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    by_resource = {c.resource: c.resource_type for c in changes}
    assert by_resource["campaign/c_brand"] == "campaign"
    assert by_resource["tiktok_ad_group/tt_infeed"] == "ad_group"


def test_zeroed_tiktok_allocation_pauses_correctly() -> None:
    plan = _plan(
        BudgetAllocation(
            arm_id="tt_topview",
            name="TopView - Awareness",
            platform="tiktok_ads",
            win_probability=0.0,
            final_share=0.0,
            daily_budget=Decimal("0"),
            note="sub pragul minim, dezactivat",
        )
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    assert changes[0].op == "PAUSE"
    assert changes[0].resource == "tiktok_ad_group/tt_topview"
