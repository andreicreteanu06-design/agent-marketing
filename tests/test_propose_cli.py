"""Teste end-to-end pentru fluxul propose / status / execute."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.guardrails.approval_gate import ApprovalGate

runner = CliRunner()


def test_propose_writes_valid_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["propose"])
    assert result.exit_code == 0

    files = list(tmp_path.glob("proposed_changes_*.json"))
    assert len(files) == 1

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["account"].startswith("mock:")
    assert payload["hard_ceiling"] == "500.00"
    assert payload["changes"]
    modules = {change["source_module"] for change in payload["changes"]}
    assert "budget" in modules
    assert float(payload["total_projected_daily_spend"]) <= float(payload["spend_limit"])

    resources = {change["resource"] for change in payload["changes"]}
    resource_types = {change["resource_type"] for change in payload["changes"]}
    assert any(r.startswith("campaign/") for r in resources)
    assert any(r.startswith("tiktok_ad_group/") for r in resources)
    assert "campaign" in resource_types
    assert "ad_group" in resource_types


def test_status_shows_pending_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert "niciun set" in runner.invoke(app, ["status"]).output

    runner.invoke(app, ["propose"])
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "Set de modificari propuse" in status.output


def test_execute_without_confirm_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["propose"])
    changeset = next(tmp_path.glob("proposed_changes_*.json"))

    result = runner.invoke(app, ["execute", "--changeset", str(changeset)])
    assert result.exit_code == 1
    assert "confirmare umana" in result.output


def test_execute_with_confirm_simulates_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["propose"])
    changeset = next(tmp_path.glob("proposed_changes_*.json"))
    before = changeset.read_text(encoding="utf-8")

    result = runner.invoke(app, ["execute", "--changeset", str(changeset), "--confirm"])
    assert result.exit_code == 0
    assert "simulat" in result.output.lower()
    assert "applied=False" in result.output
    assert changeset.read_text(encoding="utf-8") == before
    assert ApprovalGate.load(changeset).changes  # changeset intact
