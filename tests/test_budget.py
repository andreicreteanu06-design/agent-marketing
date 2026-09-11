"""Teste pentru alocarea de buget prin Thompson Sampling.

Toate testele fixeaza ``seed`` pentru reproducibilitate; tolerantele acopera
zgomotul Monte Carlo ramas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.decision.budget import ThompsonBudgetAllocator, _clip_and_normalise
from ppc_agent.decision.models import ArmStats
from ppc_agent.errors import BudgetAllocationError

_SEED = 42


def _arm(
    arm_id: str, clicks: int, conversions: int, *, platform: str = "google_ads"
) -> ArmStats:
    return ArmStats(
        arm_id=arm_id, name=arm_id, clicks=clicks, conversions=conversions, platform=platform
    )


def test_platform_defaults_to_google_ads() -> None:
    arm = ArmStats(arm_id="x", name="x", clicks=10, conversions=1)
    assert arm.platform == "google_ads"


def test_allocation_carries_arm_platform_through() -> None:
    arms = [
        _arm("c_brand", 500, 50, platform="google_ads"),
        _arm("tt_spark", 500, 30, platform="tiktok_ads"),
    ]
    plan = ThompsonBudgetAllocator().allocate(arms, 100.0, n_samples=3000, seed=_SEED)
    platforms = {a.arm_id: a.platform for a in plan.allocations}
    assert platforms["c_brand"] == "google_ads"
    assert platforms["tt_spark"] == "tiktok_ads"


def test_fixed_seed_is_deterministic() -> None:
    arms = [_arm("a", 500, 50), _arm("b", 500, 40), _arm("c", 500, 20)]
    allocator = ThompsonBudgetAllocator()
    first = allocator.allocate(arms, 100.0, n_samples=5000, seed=_SEED)
    second = allocator.allocate(arms, 100.0, n_samples=5000, seed=_SEED)
    assert first.model_dump() == second.model_dump()


def test_dominant_arm_gets_about_max_share() -> None:
    arms = [_arm("strong", 1000, 220), _arm("weak1", 1000, 10), _arm("weak2", 1000, 10)]
    allocator = ThompsonBudgetAllocator()
    plan = allocator.allocate(arms, 100.0, seed=_SEED, max_share=0.6)
    strong = next(a for a in plan.allocations if a.arm_id == "strong")
    assert strong.win_probability == pytest.approx(1.0, abs=0.01)
    assert strong.final_share == pytest.approx(0.6, abs=0.02)


def test_equal_arms_split_evenly() -> None:
    arms = [_arm("a", 200, 20), _arm("b", 200, 20), _arm("c", 200, 20)]
    allocator = ThompsonBudgetAllocator()
    plan = allocator.allocate(arms, 90.0, seed=_SEED)
    for allocation in plan.allocations:
        assert allocation.final_share == pytest.approx(1 / 3, abs=0.04)


def test_allocations_sum_to_budget_exactly() -> None:
    arms = [_arm("a", 300, 33), _arm("b", 300, 21), _arm("c", 300, 17)]
    allocator = ThompsonBudgetAllocator()
    plan = allocator.allocate(arms, 100.0, seed=_SEED)
    assert sum((a.daily_budget for a in plan.allocations), Decimal("0")) == Decimal("100.00")
    assert plan.total_allocated == Decimal("100.00")


def test_win_probabilities_sum_to_one() -> None:
    arms = [_arm("a", 400, 40), _arm("b", 400, 30), _arm("c", 400, 25), _arm("d", 400, 10)]
    allocator = ThompsonBudgetAllocator()
    plan = allocator.allocate(arms, 100.0, seed=_SEED)
    assert sum(a.win_probability for a in plan.allocations) == pytest.approx(1.0, abs=1e-6)


def test_min_share_keeps_weak_arms_visible() -> None:
    arms = [
        _arm("strong", 2000, 500),
        _arm("w1", 2000, 8),
        _arm("w2", 2000, 8),
        _arm("w3", 2000, 8),
        _arm("w4", 2000, 8),
    ]
    allocator = ThompsonBudgetAllocator()
    plan = allocator.allocate(arms, 100.0, seed=_SEED, min_share=0.05, max_share=0.6)
    for allocation in plan.allocations:
        assert allocation.final_share >= 0.05 - 1e-6


def test_low_budget_floor_disables_weakest_arms() -> None:
    arms = [_arm("strong", 1000, 200), _arm("w1", 1000, 10), _arm("w2", 1000, 10)]
    allocator = ThompsonBudgetAllocator(min_arm_daily_spend=Decimal("5"))
    plan = allocator.allocate(arms, 8.0, seed=_SEED)

    funded = [a for a in plan.allocations if a.daily_budget > 0]
    disabled = [a for a in plan.allocations if a.daily_budget == 0]
    assert len(funded) == 1
    assert len(disabled) == 2
    assert all("dezactivat" in (a.note or "") for a in disabled)
    assert sum((a.daily_budget for a in plan.allocations), Decimal("0")) == Decimal("8.00")


def test_single_arm_below_floor_keeps_budget_with_note() -> None:
    arms = [_arm("strong", 800, 120), _arm("weak", 800, 5)]
    allocator = ThompsonBudgetAllocator(min_arm_daily_spend=Decimal("5"))
    plan = allocator.allocate(arms, 3.0, seed=_SEED)
    strong = next(a for a in plan.allocations if a.arm_id == "strong")
    assert strong.daily_budget == Decimal("3.00")
    assert "sub pragul minim" in (strong.note or "")


def test_empty_arms_raises() -> None:
    with pytest.raises(BudgetAllocationError):
        ThompsonBudgetAllocator().allocate([], 100.0, seed=_SEED)


def test_negative_budget_raises() -> None:
    with pytest.raises(BudgetAllocationError):
        ThompsonBudgetAllocator().allocate([_arm("a", 10, 1)], -5.0, seed=_SEED)


def test_invalid_share_range_raises() -> None:
    with pytest.raises(BudgetAllocationError):
        ThompsonBudgetAllocator().allocate(
            [_arm("a", 10, 1)], 100.0, min_share=0.7, max_share=0.3, seed=_SEED
        )


def test_clip_and_normalise_caps_dominant_at_max() -> None:
    # [1, 0, 0] -> taiat la [0.6, 0.05, 0.05], apoi umplut la suma 1 -> [0.6, 0.2, 0.2].
    shares = _clip_and_normalise([1.0, 0.0, 0.0], 0.05, 0.6)
    assert shares[0] == pytest.approx(0.6, abs=1e-9)
    assert sum(shares) == pytest.approx(1.0, abs=1e-9)
    assert shares[1] == pytest.approx(0.2, abs=1e-9)
