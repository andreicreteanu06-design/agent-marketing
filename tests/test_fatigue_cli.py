"""Teste end-to-end pentru 'check-fatigue', inclusiv interactiunea cu 'execute'.

Scopul principal aici: dovedi ca changeset-ul scris de check-fatigue e
identic ca structura cu proposed_changes_*.json de la 'propose' - fluxul
'execute --confirm' existent il proceseaza NESCHIMBAT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.decision.fatigue_models import AdPerformanceState

runner = CliRunner()

_NOW = datetime.now(tz=UTC)


def _write_ads(path: Path, ads: list[dict[str, object]]) -> Path:
    ads_path = path / "ads.json"
    ads_path.write_text(json.dumps(ads), encoding="utf-8")
    return ads_path


def _dying_ad(ad_id: str = "ad_dying") -> dict[str, object]:
    ad = AdPerformanceState(
        ad_id=ad_id,
        platform="google",
        status="new",
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,
        target_cpa=10.0,
        conversions=0,
        impressions=1500,
        clicks=0,
        ctr=0.0,
        account_median_ctr=0.05,
        cpa_3d=0.0,
        cpa_baseline_14d=0.0,
        bad_days_last_5=0,
    )
    return ad.model_dump(mode="json")


def _healthy_ad(ad_id: str = "ad_healthy") -> dict[str, object]:
    ad = AdPerformanceState(
        ad_id=ad_id,
        platform="google",
        status="new",
        launch_time=_NOW - timedelta(hours=200),
        spend=0.0,
        target_cpa=10.0,
        conversions=0,
        impressions=0,
        clicks=0,
        ctr=0.0,
        account_median_ctr=0.05,
        cpa_3d=0.0,
        cpa_baseline_14d=0.0,
        bad_days_last_5=0,
    )
    return ad.model_dump(mode="json")


def test_check_fatigue_writes_changeset_when_ad_should_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ads_path = _write_ads(tmp_path, [_dying_ad()])

    result = runner.invoke(app, ["check-fatigue", "--input", str(ads_path)])
    assert result.exit_code == 0
    assert "PAUSE_HARD" in result.output

    files = list(tmp_path.glob("proposed_changes_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert len(payload["changes"]) == 1
    assert payload["changes"][0]["op"] == "PAUSE"
    assert payload["changes"][0]["resource"] == "ad/ad_dying"
    assert payload["changes"][0]["source_module"] == "fatigue_monitor"


def test_check_fatigue_writes_nothing_when_all_ads_are_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ads_path = _write_ads(tmp_path, [_healthy_ad()])

    result = runner.invoke(app, ["check-fatigue", "--input", str(ads_path)])
    assert result.exit_code == 0
    assert "niciun anunt de oprit" in result.output
    assert not list(tmp_path.glob("proposed_changes_*.json"))


def test_check_fatigue_missing_input_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check-fatigue", "--input", "nu_exista.json"])
    assert result.exit_code == 1


def test_check_fatigue_changeset_can_be_executed_by_existing_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dovada ca 'execute --confirm' proceseaza changeset-ul fara nicio adaptare."""
    monkeypatch.chdir(tmp_path)
    ads_path = _write_ads(tmp_path, [_dying_ad(), _healthy_ad()])

    check_result = runner.invoke(app, ["check-fatigue", "--input", str(ads_path)])
    assert check_result.exit_code == 0
    changeset_path = next(tmp_path.glob("proposed_changes_*.json"))

    execute_result = runner.invoke(
        app, ["execute", "--changeset", str(changeset_path), "--confirm"]
    )
    assert execute_result.exit_code == 0
    assert "applied=False" in execute_result.output
    assert "PAUSE ad/ad_dying" in execute_result.output
