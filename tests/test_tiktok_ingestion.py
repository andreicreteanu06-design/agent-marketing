"""Teste pentru ingestia CSV/JSON in tiktok_swipe_library.json (fara LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.errors import TikTokIngestError
from ppc_agent.ingestion.tiktok_ingestion import (
    LIBRARY_FILENAME,
    load_input_records,
    run_tiktok_ingest,
)

runner = CliRunner()

_CSV_HEADER = "niche,format,hook_audio,hook_visual,body_text,cta\n"
_CSV_ROW_1 = (
    "reparatii auto,talking_head,Nu mai merge asa,Zoom pe cutie,"
    "Am aratat piesa uzata pe camera,Suna acum\n"
)
_CSV_ROW_2 = (
    "bijuterii bratara,unboxing,Am testat sub apa,Despachetare,"
    "Argint 925 verificat cu lupa,Comanda din link\n"
)


def _write_csv(path: Path, rows: str = _CSV_ROW_1 + _CSV_ROW_2) -> Path:
    csv_path = path / "input.csv"
    csv_path.write_text(_CSV_HEADER + rows, encoding="utf-8")
    return csv_path


def test_load_valid_csv_maps_columns_correctly(tmp_path: Path) -> None:
    records = load_input_records(_write_csv(tmp_path))
    assert len(records) == 2
    first = records[0]
    assert first.niche == "reparatii auto"
    assert first.format == "talking_head"
    assert first.hook_audio == "Nu mai merge asa"
    assert first.hook_visual == "Zoom pe cutie"
    assert first.mechanism_proof == "Am aratat piesa uzata pe camera"
    assert first.cta_text == "Suna acum"
    assert first.days_active_proxy == 14
    assert first.ad_id


def test_load_csv_missing_column_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("niche,format\nx,y\n", encoding="utf-8")
    with pytest.raises(TikTokIngestError):
        load_input_records(csv_path)


def test_load_csv_empty_file_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text(_CSV_HEADER, encoding="utf-8")
    with pytest.raises(TikTokIngestError):
        load_input_records(csv_path)


def test_load_json_input(tmp_path: Path) -> None:
    json_path = tmp_path / "input.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "ad_id": "manual_1",
                    "niche": "test niche",
                    "format": "test_format",
                    "days_active_proxy": 40,
                    "hook_visual": "v",
                    "hook_audio": "a",
                    "mechanism_proof": "m",
                    "cta_text": "c",
                }
            ]
        ),
        encoding="utf-8",
    )
    records = load_input_records(json_path)
    assert len(records) == 1
    assert records[0].ad_id == "manual_1"
    assert records[0].days_active_proxy == 40


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    json_path = tmp_path / "bad.json"
    json_path.write_text("{ nu e json", encoding="utf-8")
    with pytest.raises(TikTokIngestError):
        load_input_records(json_path)


def test_load_unknown_extension_raises(tmp_path: Path) -> None:
    bad_path = tmp_path / "input.txt"
    bad_path.write_text("orice", encoding="utf-8")
    with pytest.raises(TikTokIngestError):
        load_input_records(bad_path)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TikTokIngestError):
        load_input_records(tmp_path / "nu_exista.csv")


def test_run_tiktok_ingest_writes_library(tmp_path: Path) -> None:
    added = run_tiktok_ingest(_write_csv(tmp_path), tmp_path)
    assert len(added) == 2

    library = json.loads((tmp_path / LIBRARY_FILENAME).read_text(encoding="utf-8"))
    assert len(library["entries"]) == 2


def test_run_tiktok_ingest_dedupes_by_ad_id(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path)
    first_added = run_tiktok_ingest(csv_path, tmp_path)
    second_added = run_tiktok_ingest(csv_path, tmp_path)

    assert len(first_added) == 2
    assert len(second_added) == 0  # acelasi continut -> acelasi ad_id -> nimic nou

    library = json.loads((tmp_path / LIBRARY_FILENAME).read_text(encoding="utf-8"))
    assert len(library["entries"]) == 2  # nu s-a duplicat


def test_stable_ad_id_is_deterministic_across_runs(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path)
    first = load_input_records(csv_path)
    second = load_input_records(csv_path)
    assert [r.ad_id for r in first] == [r.ad_id for r in second]


def test_cli_ingest_tiktok_writes_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    csv_path = _write_csv(tmp_path)
    result = runner.invoke(app, ["ingest-tiktok", "--input", str(csv_path)])
    assert result.exit_code == 0
    assert (tmp_path / LIBRARY_FILENAME).is_file()


def test_cli_ingest_tiktok_missing_file_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ingest-tiktok", "--input", "nu_exista.csv"])
    assert result.exit_code == 1
