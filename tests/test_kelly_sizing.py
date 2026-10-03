"""Teste deterministe pentru criteriul lui Kelly si dimensionarea plafonului zilnic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.decision.kelly_sizing import calculate_kelly_fraction, size_daily_budget
from ppc_agent.decision.models import ArmStats

_CEILING = Decimal("500.00")


def _arm(cost: str, revenue: str, *, clicks: int = 1000, conversions: int = 30) -> ArmStats:
    return ArmStats(
        arm_id="a",
        name="a",
        clicks=clicks,
        conversions=conversions,
        cost=Decimal(cost),
        revenue=Decimal(revenue),
    )


@pytest.mark.parametrize(
    ("win_prob", "roas_odds", "fraction", "expected"),
    [
        (0.7, 1.0, 0.5, 0.2),    # full = (0.7 - 0.3)/1 = 0.4 ; half = 0.2
        (0.5, 1.0, 0.5, 0.0),    # break-even
        (0.3, 1.0, 0.5, -0.2),   # dezavantaj
        (0.6, 2.0, 0.5, 0.2),    # full = (1.2 - 0.4)/2 = 0.4 ; half = 0.2
        (0.7, 1.0, 1.0, 0.4),    # Kelly complet
        (0.9, 0.0, 0.5, 0.0),    # b == 0 -> mentine
        (0.9, -0.4, 0.5, -0.2),  # b < 0 -> semnal de reducere
    ],
)
def test_calculate_kelly_fraction(
    win_prob: float, roas_odds: float, fraction: float, expected: float
) -> None:
    assert calculate_kelly_fraction(win_prob, roas_odds, fraction) == pytest.approx(
        expected
    )


def test_kelly_fraction_is_clamped_to_unit_interval() -> None:
    assert calculate_kelly_fraction(1.5, 1.0) == pytest.approx(0.5)  # p taiat la 1
    assert calculate_kelly_fraction(0.01, 0.001, fraction=1.0) == -1.0


def test_positive_edge_scales_cap_up_under_ceiling() -> None:
    sizing = size_daily_budget(
        [_arm("1000", "2500")], baseline_cap=Decimal("50.00"), hard_ceiling=_CEILING
    )
    assert sizing.edge == "pozitiv"
    assert sizing.account_roas == pytest.approx(2.5)
    assert sizing.sized_daily_cap > sizing.baseline_cap
    assert sizing.sized_daily_cap <= _CEILING
    assert "Half-Kelly" in sizing.rationale


def test_negative_edge_scales_cap_down() -> None:
    sizing = size_daily_budget(
        [_arm("1000", "700")], baseline_cap=Decimal("50.00"), hard_ceiling=_CEILING
    )
    assert sizing.edge == "negativ"
    assert sizing.sized_daily_cap < sizing.baseline_cap
    assert sizing.sized_daily_cap >= Decimal("1.00")


def test_break_even_keeps_cap() -> None:
    sizing = size_daily_budget(
        [_arm("1000", "1000")], baseline_cap=Decimal("50.00"), hard_ceiling=_CEILING
    )
    assert sizing.edge == "neutru"
    assert sizing.sized_daily_cap == Decimal("50.00")


def test_no_data_holds_cap_at_baseline() -> None:
    sizing = size_daily_budget(
        [_arm("0", "0", clicks=0, conversions=0)],
        baseline_cap=Decimal("50.00"),
        hard_ceiling=_CEILING,
    )
    assert sizing.edge == "date_insuficiente"
    assert sizing.sized_daily_cap == Decimal("50.00")


def test_hard_ceiling_is_never_exceeded() -> None:
    sizing = size_daily_budget(
        [_arm("1000", "5000")],
        baseline_cap=Decimal("480.00"),
        hard_ceiling=_CEILING,
    )
    assert sizing.edge == "pozitiv"
    assert sizing.sized_daily_cap == _CEILING


def test_baseline_above_ceiling_is_clamped() -> None:
    sizing = size_daily_budget(
        [_arm("1000", "1000")],
        baseline_cap=Decimal("900.00"),
        hard_ceiling=_CEILING,
    )
    assert sizing.baseline_cap == _CEILING
    assert sizing.sized_daily_cap <= _CEILING


def test_half_kelly_less_aggressive_than_full() -> None:
    arms = [_arm("1000", "3000")]
    half = size_daily_budget(
        arms, baseline_cap=Decimal("50.00"), hard_ceiling=_CEILING, kelly_fraction=0.5
    )
    full = size_daily_budget(
        arms, baseline_cap=Decimal("50.00"), hard_ceiling=_CEILING, kelly_fraction=1.0
    )
    assert half.multiplier < full.multiplier
    assert half.sized_daily_cap < full.sized_daily_cap


def test_a_shop_covering_its_ads_but_below_its_margin_gets_less_not_more() -> None:
    """ROAS 1,8: fata de pragul 1 pare castig (+buget), fata de marja de 40% (prag 2,5)
    e pierdere (-buget)."""
    arms = [_arm(cost="2000", revenue="3600")]
    naive = size_daily_budget(arms, baseline_cap=Decimal("50"), hard_ceiling=Decimal("500"))
    shop = size_daily_budget(
        arms,
        baseline_cap=Decimal("50"),
        hard_ceiling=Decimal("500"),
        break_even_roas=Decimal("2.5"),
    )
    assert naive.edge == "pozitiv" and naive.sized_daily_cap > Decimal("50")
    assert shop.edge == "negativ" and shop.sized_daily_cap < Decimal("50")
    assert "prag de rentabilitate 2.50" in shop.rationale
