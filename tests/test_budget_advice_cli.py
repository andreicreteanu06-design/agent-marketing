"""Test pentru comanda ``budget-advice`` (consilier de capacitate, fara provideri)."""

from __future__ import annotations

from typer.testing import CliRunner

from ppc_agent.cli import app

runner = CliRunner()


def test_budget_advice_prints_capacity_section() -> None:
    result = runner.invoke(
        app, ["budget-advice", "--daily-budget", "20.00", "--target-cpa", "150.00"]
    )
    assert result.exit_code == 0
    assert "Capacitate per buget" in result.output
    assert "tier=micro" in result.output
    assert "maxim 1" in result.output


def test_budget_advice_rejects_zero_budget() -> None:
    result = runner.invoke(
        app, ["budget-advice", "--daily-budget", "0", "--target-cpa", "50.00"]
    )
    assert result.exit_code == 1
    assert "calcul esuat" in result.output


def test_budget_advice_accepts_custom_evaluation_horizon() -> None:
    result = runner.invoke(
        app,
        [
            "budget-advice",
            "--daily-budget",
            "100.00",
            "--target-cpa",
            "50.00",
            "--evaluation-days",
            "14",
        ],
    )
    assert result.exit_code == 0
    assert "orizont 14z" in result.output
