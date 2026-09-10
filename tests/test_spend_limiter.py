"""Teste pentru limitatorul absolut de cheltuiala zilnica."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.errors import SpendLimitExceeded
from ppc_agent.guardrails.spend_limiter import HARD_CEILING, AbsoluteSpendLimiter


def test_spend_at_limit_passes() -> None:
    limiter = AbsoluteSpendLimiter(Decimal("50.00"))
    limiter.check(Decimal("50.00"))  # nu ridica


def test_spend_one_cent_over_raises() -> None:
    limiter = AbsoluteSpendLimiter(Decimal("50.00"))
    with pytest.raises(SpendLimitExceeded):
        limiter.check(Decimal("50.01"))


def test_spend_under_limit_passes() -> None:
    limiter = AbsoluteSpendLimiter(Decimal("50.00"))
    limiter.check(Decimal("12.34"))


def test_config_above_hard_ceiling_raises_at_construction() -> None:
    with pytest.raises(SpendLimitExceeded):
        AbsoluteSpendLimiter(HARD_CEILING + Decimal("0.01"))


def test_config_equal_to_hard_ceiling_is_allowed() -> None:
    limiter = AbsoluteSpendLimiter(HARD_CEILING)
    assert limiter.max_daily_spend == HARD_CEILING
    limiter.check(HARD_CEILING)


def test_non_positive_limit_raises() -> None:
    with pytest.raises(SpendLimitExceeded):
        AbsoluteSpendLimiter(Decimal("0"))
    with pytest.raises(SpendLimitExceeded):
        AbsoluteSpendLimiter(Decimal("-1"))


def test_hard_ceiling_is_exposed_and_fixed() -> None:
    limiter = AbsoluteSpendLimiter(Decimal("100.00"))
    assert limiter.hard_ceiling == Decimal("500.00")
    assert limiter.hard_ceiling == HARD_CEILING
