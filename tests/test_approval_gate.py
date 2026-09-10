"""Teste pentru ``ApprovalGate`` — nicio scriere fara changeset + confirmare."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ppc_agent.errors import ApprovalRequiredError, SpendLimitExceeded
from ppc_agent.guardrails.approval_gate import ApprovalGate
from ppc_agent.guardrails.models import ChangeSet, ProposedChange
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter


def _budget_change(resource: str, spend: str) -> ProposedChange:
    return ProposedChange(
        op="UPDATE",
        resource=resource,
        resource_type="campaign",
        after={"daily_budget": spend},
        projected_daily_spend=Decimal(spend),
        rationale="test",
        source_module="budget",
    )


def _gate(tmp_path: Path, limit: str = "50.00", account: str = "mock:acc") -> ApprovalGate:
    return ApprovalGate(
        account=account,
        spend_limiter=AbsoluteSpendLimiter(Decimal(limit)),
        output_dir=tmp_path,
    )


def test_propose_buffers_without_writing(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose(_budget_change("campaign/a", "10.00"))
    gate.propose(_budget_change("campaign/b", "20.00"))
    assert len(gate.pending) == 2
    assert list(tmp_path.glob("*.json")) == []


def test_flush_writes_changeset_matching_schema(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose_many(
        [_budget_change("campaign/a", "30.00"), _budget_change("campaign/b", "20.00")]
    )
    path = gate.flush()

    assert path.exists()
    assert path.name.startswith("proposed_changes_")
    loaded = ApprovalGate.load(path)
    assert isinstance(loaded, ChangeSet)
    assert loaded.account == "mock:acc"
    assert loaded.total_projected_daily_spend == Decimal("50.00")
    assert loaded.spend_limit == Decimal("50.00")
    assert loaded.hard_ceiling == Decimal("500.00")
    assert [c.resource for c in loaded.changes] == ["campaign/a", "campaign/b"]


def test_flush_round_trips(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose(_budget_change("campaign/a", "12.50"))
    path = gate.flush()

    loaded = ApprovalGate.load(path)
    assert loaded.total_projected_daily_spend == Decimal("12.50")
    assert len(loaded.changes) == 1
    assert loaded.changes[0].projected_daily_spend == Decimal("12.50")
    assert ApprovalGate.load(path).model_dump_json() == loaded.model_dump_json()


def test_flush_blocked_when_over_spend_limit_writes_nothing(tmp_path: Path) -> None:
    gate = _gate(tmp_path, limit="50.00")
    gate.propose_many(
        [_budget_change("campaign/a", "40.00"), _budget_change("campaign/b", "20.00")]
    )
    with pytest.raises(SpendLimitExceeded):
        gate.flush()
    assert list(tmp_path.glob("*.json")) == []


def test_execute_without_confirmation_raises(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose(_budget_change("campaign/a", "10.00"))
    path = gate.flush()
    with pytest.raises(ApprovalRequiredError):
        gate.execute(path, confirmed=False)


def test_execute_with_confirmation_only_simulates(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose_many(
        [_budget_change("campaign/a", "10.00"), _budget_change("campaign/b", "5.00")]
    )
    path = gate.flush()
    before = path.read_text(encoding="utf-8")

    report = gate.execute(path, confirmed=True)

    assert report.applied is False
    assert len(report.simulated_calls) == 2
    assert all("SIMULAT" in call for call in report.simulated_calls)
    assert path.read_text(encoding="utf-8") == before  # fisierul neatins


def test_execute_rejects_truthy_non_true(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose(_budget_change("campaign/a", "10.00"))
    path = gate.flush()
    with pytest.raises(ApprovalRequiredError):
        gate.execute(path, confirmed=1)  # type: ignore[arg-type]


def test_two_flushes_produce_distinct_files(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    gate.propose(_budget_change("campaign/a", "10.00"))
    first = gate.flush()
    second = gate.flush()
    assert first != second
    assert len(list(tmp_path.glob("proposed_changes_*.json"))) == 2
