"""Teste pentru consilierul de capacitate per buget (conturi cu buget mic)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.decision.budget_strategy import recommend_arm_capacity
from ppc_agent.decision.fatigue_monitor import new_ad_hard_kill_spend_multiplier
from ppc_agent.errors import BudgetAllocationError


def test_hard_kill_multiplier_matches_gate_b() -> None:
    """Garanteaza ca cele doua module raman sincronizate pe acelasi prag."""
    assert new_ad_hard_kill_spend_multiplier() == 2.0


def test_micro_budget_supports_a_single_arm() -> None:
    """15 lei/zi la target_cpa 100 -> Gate B (2x=200) ar dura >7 zile pe un singur brat."""
    advice = recommend_arm_capacity(Decimal("15.00"), Decimal("100.00"))
    assert advice.tier == "micro"
    assert advice.recommended_max_concurrent_arms == 1
    assert advice.recommended_min_arm_daily_spend == Decimal("28.57")


def test_larger_budget_supports_multiple_arms() -> None:
    """100 lei/zi la target_cpa 50 -> prag/brat ~14.29, deci pana la 6 brate."""
    advice = recommend_arm_capacity(Decimal("100.00"), Decimal("50.00"))
    assert advice.recommended_min_arm_daily_spend == Decimal("14.29")
    assert advice.recommended_max_concurrent_arms == 6
    assert advice.tier == "scale"


def test_standard_tier_boundary() -> None:
    """Exact 4 brate posibile -> tier 'standard' (limita superioara a benzii)."""
    advice = recommend_arm_capacity(Decimal("120.00"), Decimal("100.00"))
    assert advice.recommended_min_arm_daily_spend == Decimal("28.57")
    assert advice.recommended_max_concurrent_arms == 4
    assert advice.tier == "standard"


def test_custom_evaluation_horizon_changes_threshold() -> None:
    """Un orizont mai lung (14 zile) injumatateste pragul minim per brat."""
    week = recommend_arm_capacity(Decimal("100.00"), Decimal("50.00"), target_evaluation_days=7.0)
    two_weeks = recommend_arm_capacity(
        Decimal("100.00"), Decimal("50.00"), target_evaluation_days=14.0
    )
    assert float(two_weeks.recommended_min_arm_daily_spend) == pytest.approx(
        float(week.recommended_min_arm_daily_spend) / 2, abs=0.01
    )
    assert two_weeks.recommended_max_concurrent_arms >= week.recommended_max_concurrent_arms


def test_accepts_float_inputs_like_decimal() -> None:
    advice = recommend_arm_capacity(20.0, 50.0)
    assert advice.daily_budget == Decimal("20.0")
    assert advice.target_cpa == Decimal("50.0")


@pytest.mark.parametrize(
    "daily_budget,target_cpa,evaluation_days",
    [
        (Decimal("0"), Decimal("50.00"), 7.0),
        (Decimal("-10"), Decimal("50.00"), 7.0),
        (Decimal("20.00"), Decimal("0"), 7.0),
        (Decimal("20.00"), Decimal("50.00"), 0.0),
        (Decimal("20.00"), Decimal("50.00"), -1.0),
    ],
)
def test_rejects_non_positive_inputs(
    daily_budget: Decimal, target_cpa: Decimal, evaluation_days: float
) -> None:
    with pytest.raises(BudgetAllocationError):
        recommend_arm_capacity(daily_budget, target_cpa, target_evaluation_days=evaluation_days)
