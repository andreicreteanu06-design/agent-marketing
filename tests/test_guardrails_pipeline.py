"""Teste pentru build_proposed_changes() - in special denumirea resursei per platforma.

Nu exista alt fisier care sa testeze direct aceasta functie (doar indirect, prin
CLI, in test_propose_cli.py) - acestea sunt testele unitare dedicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ppc_agent.alignment.models import LiquidityPlan
from ppc_agent.decision.fatigue_models import AdPerformanceState
from ppc_agent.decision.models import BudgetAllocation, BudgetPlan
from ppc_agent.guardrails.pipeline import build_fatigue_changes, build_proposed_changes
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


def test_meta_ads_allocation_uses_ad_set_resource_naming() -> None:
    plan = _plan(
        BudgetAllocation(
            arm_id="as_brand",
            name="Retargeting brand",
            platform="meta_ads",
            win_probability=0.5,
            final_share=1.0,
            daily_budget=Decimal("25.00"),
        )
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    assert len(changes) == 1
    assert changes[0].resource == "meta_ad_set/as_brand"
    assert changes[0].resource_type == "ad_set"


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
            win_probability=0.5,
            final_share=0.4,
            daily_budget=Decimal("25.00"),
        ),
        BudgetAllocation(
            arm_id="tt_infeed",
            name="In-Feed - Conversii",
            platform="tiktok_ads",
            win_probability=0.3,
            final_share=0.3,
            daily_budget=Decimal("15.00"),
        ),
        BudgetAllocation(
            arm_id="as_brand",
            name="Retargeting brand",
            platform="meta_ads",
            win_probability=0.2,
            final_share=0.3,
            daily_budget=Decimal("15.00"),
        ),
    )
    changes = build_proposed_changes(
        budget_plan=plan, negatives=_EMPTY_NEGATIVES, liquidity=_EMPTY_LIQUIDITY
    )
    by_resource = {c.resource: c.resource_type for c in changes}
    assert by_resource["campaign/c_brand"] == "campaign"
    assert by_resource["tiktok_ad_group/tt_infeed"] == "ad_group"
    assert by_resource["meta_ad_set/as_brand"] == "ad_set"


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


_NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)


def _ad(**overrides: object) -> AdPerformanceState:
    defaults: dict[str, object] = dict(
        ad_id="ad_1",
        platform="google",
        status="new",
        launch_time=_NOW - timedelta(hours=200),
        spend=0.0,
        target_cpa=10.0,
        conversions=0,
        impressions=0,
        clicks=0,
        ctr=0.0,
        account_median_ctr=0.05,
        cpa_3d=0.0,
        cpa_baseline_14d=0.0,
        bad_days_last_5=0,
    )
    defaults.update(overrides)
    return AdPerformanceState.model_validate(defaults)


def test_build_fatigue_changes_produces_pause_for_hard_kill() -> None:
    ad = _ad(
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,
        conversions=0,
        impressions=1500,
    )
    changes = build_fatigue_changes([ad], _NOW)
    assert len(changes) == 1
    assert changes[0].op == "PAUSE"
    assert changes[0].resource == "ad/ad_1"
    assert changes[0].resource_type == "ad"
    assert changes[0].source_module == "fatigue_monitor"
    assert changes[0].projected_daily_spend == Decimal("0")
    assert "PAUSE_HARD" in changes[0].rationale


def test_build_fatigue_changes_skips_continue_and_hold_for_lag() -> None:
    healthy = _ad()  # baseline "sigur" - CONTINUE
    holding = _ad(launch_time=_NOW - timedelta(hours=50), spend=15.0, conversions=0)
    changes = build_fatigue_changes([healthy, holding], _NOW)
    assert changes == []


def test_build_fatigue_changes_handles_mixed_ad_list() -> None:
    dying = _ad(
        ad_id="ad_dying",
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,
        conversions=0,
        impressions=1500,
    )
    healthy = _ad(ad_id="ad_healthy")
    changes = build_fatigue_changes([dying, healthy], _NOW)
    assert [c.resource for c in changes] == ["ad/ad_dying"]
