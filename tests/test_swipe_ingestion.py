"""Teste pentru ingestia CSV universala in omnichannel_swipe_library (fara LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.errors import SwipeIngestError
from ppc_agent.ingestion.swipe_ingestion import _load_csv, run_swipe_ingest

runner = CliRunner()

_CSV_HEADER = (
    "niche,format,longevity_days,variation_count,performance_signal,"
    "hook_type,hook_text,problem_agitation,mechanism_proof,offer_cta\n"
)
_CSV_ROW_1 = (
    "reparatii auto,search_text,60,5,active_60_days,high_intent_question,"
    "Cutie de viteze cu probleme?,Simptomele ignorate costa mai mult,"
    "Diagnoza computerizata cu cost fix,Programeaza acum\n"
)
_CSV_ROW_2 = (
    "bijuterii bratara,advertorial_static,,,active_recent,relatable_pain_point,"
    "Bratarile ieftine se innegresc,Am testat cinci modele diferite,"
    "Argint 925 verificat cu test de aciditate,Comanda din link\n"
)

_MINIMAL_SWIPE_FILE: dict[str, object] = {
    "_comment": "test fixture",
    "frameworks": [],
    "tiktok_swipe_library": [],
    "omnichannel_swipe_library": [],
}


def _write_csv(path: Path, rows: str = _CSV_ROW_1 + _CSV_ROW_2) -> Path:
    csv_path = path / "input.csv"
    csv_path.write_text(_CSV_HEADER + rows, encoding="utf-8")
    return csv_path


def _write_swipe_file(path: Path, content: dict[str, object] | None = None) -> Path:
    swipe_path = path / "swipe_file.json"
    swipe_path.write_text(
        json.dumps(content if content is not None else _MINIMAL_SWIPE_FILE), encoding="utf-8"
    )
    return swipe_path


def test_load_csv_maps_columns_and_derives_ad_id(tmp_path: Path) -> None:
    records = _load_csv("google", _write_csv(tmp_path))
    assert len(records) == 2
    first = records[0]
    assert first.platform == "google"
    assert first.niche == "reparatii auto"
    assert first.format == "search_text"
    assert first.longevity_days == 60
    assert first.variation_count == 5
    assert first.performance_signal == "active_60_days"
    assert first.hook_type == "high_intent_question"
    assert first.offer_cta == "Programeaza acum"
    assert first.ad_id.startswith("om_google_")


def test_load_csv_optional_ints_are_none_when_blank(tmp_path: Path) -> None:
    records = _load_csv("meta", _write_csv(tmp_path))
    second = records[1]
    assert second.longevity_days is None
    assert second.variation_count is None


def test_load_csv_missing_column_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("niche,format\nx,y\n", encoding="utf-8")
    with pytest.raises(SwipeIngestError):
        _load_csv("google", csv_path)


def test_load_csv_empty_file_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text(_CSV_HEADER, encoding="utf-8")
    with pytest.raises(SwipeIngestError):
        _load_csv("google", csv_path)


def test_load_csv_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SwipeIngestError):
        _load_csv("google", tmp_path / "nu_exista.csv")


def test_stable_ad_id_is_deterministic_and_platform_scoped(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path)
    google_ids = [r.ad_id for r in _load_csv("google", csv_path)]
    meta_ids = [r.ad_id for r in _load_csv("meta", csv_path)]
    again = [r.ad_id for r in _load_csv("google", csv_path)]
    assert google_ids == again
    assert set(google_ids).isdisjoint(meta_ids)


def test_run_swipe_ingest_writes_into_omnichannel_library(tmp_path: Path) -> None:
    swipe_path = _write_swipe_file(tmp_path)
    added = run_swipe_ingest(_write_csv(tmp_path), "google", swipe_path)
    assert len(added) == 2

    raw = json.loads(swipe_path.read_text(encoding="utf-8"))
    assert len(raw["omnichannel_swipe_library"]) == 2
    assert all(item["platform"] == "google" for item in raw["omnichannel_swipe_library"])


def test_run_swipe_ingest_preserves_other_keys(tmp_path: Path) -> None:
    swipe_path = _write_swipe_file(
        tmp_path,
        {
            "_comment": "nu ma sterge",
            "frameworks": [{"keep": "me"}],
            "tiktok_swipe_library": [{"keep": "me too"}],
            "omnichannel_swipe_library": [],
        },
    )
    run_swipe_ingest(_write_csv(tmp_path), "google", swipe_path)

    raw = json.loads(swipe_path.read_text(encoding="utf-8"))
    assert raw["_comment"] == "nu ma sterge"
    assert raw["frameworks"] == [{"keep": "me"}]
    assert raw["tiktok_swipe_library"] == [{"keep": "me too"}]


def test_run_swipe_ingest_dedupes_by_ad_id(tmp_path: Path) -> None:
    swipe_path = _write_swipe_file(tmp_path)
    csv_path = _write_csv(tmp_path)
    first_added = run_swipe_ingest(csv_path, "tiktok", swipe_path)
    second_added = run_swipe_ingest(csv_path, "tiktok", swipe_path)

    assert len(first_added) == 2
    assert len(second_added) == 0

    raw = json.loads(swipe_path.read_text(encoding="utf-8"))
    assert len(raw["omnichannel_swipe_library"]) == 2


def test_run_swipe_ingest_appends_to_existing_entries(tmp_path: Path) -> None:
    swipe_path = _write_swipe_file(
        tmp_path,
        {
            "_comment": "x",
            "frameworks": [],
            "tiktok_swipe_library": [],
            "omnichannel_swipe_library": [
                {
                    "ad_id": "already_here",
                    "platform": "meta",
                    "niche": "altceva",
                    "format": "x",
                    "longevity_days": None,
                    "variation_count": None,
                    "performance_signal": "active",
                    "hook_type": "x",
                    "hook_text": "x",
                    "problem_agitation": "x",
                    "mechanism_proof": "x",
                    "offer_cta": "x",
                }
            ],
        },
    )
    added = run_swipe_ingest(_write_csv(tmp_path), "google", swipe_path)
    assert len(added) == 2

    raw = json.loads(swipe_path.read_text(encoding="utf-8"))
    assert len(raw["omnichannel_swipe_library"]) == 3
    ids = {item["ad_id"] for item in raw["omnichannel_swipe_library"]}
    assert "already_here" in ids


def test_run_swipe_ingest_missing_swipe_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SwipeIngestError):
        run_swipe_ingest(_write_csv(tmp_path), "google", tmp_path / "nu_exista.json")


def test_run_swipe_ingest_malformed_swipe_file_raises(tmp_path: Path) -> None:
    swipe_path = tmp_path / "swipe_file.json"
    swipe_path.write_text("{ nu e json", encoding="utf-8")
    with pytest.raises(SwipeIngestError):
        run_swipe_ingest(_write_csv(tmp_path), "google", swipe_path)


def test_run_swipe_ingest_invalid_row_raises(tmp_path: Path) -> None:
    swipe_path = _write_swipe_file(tmp_path)
    csv_path = tmp_path / "bad_row.csv"
    csv_path.write_text(
        _CSV_HEADER
        + "auto,search_text,nu-e-numar,5,active,intent,hook,problema,dovada,cta\n",
        encoding="utf-8",
    )
    with pytest.raises(SwipeIngestError):
        run_swipe_ingest(csv_path, "google", swipe_path)


def test_cli_ingest_swipes_writes_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    swipe_path = _write_swipe_file(tmp_path)
    monkeypatch.setattr(
        "ppc_agent.ingestion.swipe_ingestion.default_swipe_path", lambda: swipe_path
    )
    monkeypatch.setattr("ppc_agent.cli.default_swipe_path", lambda: swipe_path)

    csv_path = _write_csv(tmp_path)
    result = runner.invoke(app, ["ingest-swipes", "--csv", str(csv_path), "--platform", "google"])
    assert result.exit_code == 0

    raw = json.loads(swipe_path.read_text(encoding="utf-8"))
    assert len(raw["omnichannel_swipe_library"]) == 2


def test_cli_ingest_swipes_missing_file_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    swipe_path = _write_swipe_file(tmp_path)
    monkeypatch.setattr(
        "ppc_agent.ingestion.swipe_ingestion.default_swipe_path", lambda: swipe_path
    )
    result = runner.invoke(
        app, ["ingest-swipes", "--csv", "nu_exista.csv", "--platform", "google"]
    )
    assert result.exit_code == 1
