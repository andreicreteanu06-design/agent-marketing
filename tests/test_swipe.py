"""Teste pentru incarcarea si recuperarea din swipe_file.json (RAG local)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.copywriter.swipe import (
    default_swipe_path,
    load_swipe_file,
    retrieve_framework,
)
from ppc_agent.errors import SwipeFileError


def test_default_swipe_file_loads_and_has_four_styles() -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert set(swipe.styles()) == {"pas", "status", "fomo", "aida"}


@pytest.mark.parametrize(
    ("trigger", "expected_style"),
    [
        ("frica", "pas"),
        ("urgenta / defectiuni auto", "pas"),
        ("status", "status"),
        ("statut si validare sociala", "status"),
        ("fomo", "fomo"),
        ("stoc limitat, oferta pe timp scurt", "fomo"),
        ("aida", "aida"),
        ("curiozitate si beneficiu masurabil", "aida"),
    ],
)
def test_retrieve_framework_by_trigger(trigger: str, expected_style: str) -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert retrieve_framework(swipe, trigger).style == expected_style


def test_retrieve_unknown_trigger_raises() -> None:
    swipe = load_swipe_file(default_swipe_path())
    with pytest.raises(SwipeFileError):
        retrieve_framework(swipe, "xyzzy plugh nimic")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SwipeFileError):
        load_swipe_file(tmp_path / "nu_exista.json")


def test_malformed_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "swipe_file.json"
    bad.write_text("{ nu e json", encoding="utf-8")
    with pytest.raises(SwipeFileError):
        load_swipe_file(bad)


def test_schema_violation_raises(tmp_path: Path) -> None:
    bad = tmp_path / "swipe_file.json"
    bad.write_text('{"frameworks": []}', encoding="utf-8")
    with pytest.raises(SwipeFileError):
        load_swipe_file(bad)
