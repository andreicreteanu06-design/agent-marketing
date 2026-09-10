"""Test end-to-end pentru comanda ``plan`` pe furnizori mock."""

from __future__ import annotations

from decimal import Decimal

from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.config import AppConfig, Settings
from ppc_agent.decision.pipeline import run_plan
from ppc_agent.providers.factory import ProviderFactory

runner = CliRunner()


def test_plan_command_runs_and_prints_sections() -> None:
    result = runner.invoke(app, ["plan"])
    assert result.exit_code == 0
    for section in (
        "Alocare buget",
        "Thompson Sampling",
        "Atribuire Markov",
        "efect eliminare",
        "last-click",
    ):
        assert section in result.output


def test_plan_budget_respects_configured_max_daily_spend() -> None:
    config = AppConfig(settings=Settings(_env_file=None))
    config.budget.max_daily_spend = Decimal("37.00")
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)

    total = sum((a.daily_budget for a in plan.budget_plan.allocations), Decimal("0"))
    assert total == Decimal("37.00")
    assert plan.budget_plan.daily_budget == Decimal("37.00")


def test_plan_is_reproducible() -> None:
    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    first = run_plan(factory, config, seed=7, n_samples=3000)
    second = run_plan(factory, config, seed=7, n_samples=3000)
    assert first.model_dump() == second.model_dump()
