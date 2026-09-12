"""Teste pentru ``_app_config_for`` (constructia AppConfig dintr-un ClientAccount)."""

from __future__ import annotations

from decimal import Decimal

from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import ClientAccount


def test_default_lead_value_feeds_budget_target_cpa() -> None:
    """default_lead_value alimenteaza target_cpa - activeaza sfatul de capacitate
    per buget (decision.budget_strategy) automat, fara camp separat pe client."""
    account = ClientAccount(
        tenant_id=1,
        name="Client Test",
        max_daily_spend=Decimal("20.00"),
        default_lead_value=Decimal("150.00"),
    )
    config = _app_config_for(account)
    assert config.budget.max_daily_spend == Decimal("20.00")
    assert config.budget.target_cpa == Decimal("150.00")
