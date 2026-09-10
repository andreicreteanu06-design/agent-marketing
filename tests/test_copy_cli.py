"""Teste end-to-end pentru comanda ``copy`` si coada HITL proposed_ads_queue.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app

runner = CliRunner()

_ARGS = [
    "copy",
    "--keyword",
    "program facturare",
    "--usp",
    "Program de facturare cu e-Factura inclusa, de la 29 lei pe luna",
    "--trigger",
    "fomo",
]


def test_copy_appends_to_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, _ARGS)
    assert result.exit_code == 0

    queue_path = tmp_path / "proposed_ads_queue.json"
    assert queue_path.is_file()
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(payload["queue"]) == 1

    entry = payload["queue"][0]
    assert entry["status"] == "pending_review"
    assert entry["framework_style"] == "fomo"
    assert entry["target_keyword"] == "program facturare"
    ad = entry["ad"]
    assert len(ad["headline_1"]) <= 30
    assert len(ad["description"]) <= 90
    assert "program facturare" in (ad["headline_1"] + " " + ad["headline_2"]).lower()


def test_copy_appends_multiple_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, _ARGS)
    runner.invoke(app, [*_ARGS[:2], "curs excel", *_ARGS[3:]])

    payload = json.loads((tmp_path / "proposed_ads_queue.json").read_text("utf-8"))
    assert len(payload["queue"]) == 2
    assert {e["target_keyword"] for e in payload["queue"]} == {
        "program facturare",
        "curs excel",
    }


def test_copy_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*_ARGS, "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert not (tmp_path / "proposed_ads_queue.json").exists()


def test_copy_keyword_too_long_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "copy",
            "--keyword",
            "reparatii cutii de viteze automate pentru masini germane",
            "--usp",
            "test",
            "--trigger",
            "pas",
        ],
    )
    assert result.exit_code == 1
