"""Teste pentru integrarea Flick (asamblare video) — mock, offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppc_agent.creative.video_engine import (
    FlickVideoBuilder,
    MockFlickBuilder,
    manifest_path,
)
from ppc_agent.errors import SetupRequiredError, VideoAssemblyError

_SUBTITLE = "Simti smucituri in cutia auto? Programeaza o diagnoza astazi."


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    broll = tmp_path / "broll.mp4"
    broll.write_bytes(b"fake broll")
    wav = tmp_path / "vo.wav"
    wav.write_bytes(b"fake wav")
    return broll, wav


def test_mock_builds_mp4_and_manifest(tmp_path: Path) -> None:
    broll, wav = _inputs(tmp_path)
    out = tmp_path / "out" / "ad.mp4"

    written = MockFlickBuilder().build(
        broll_path=broll, voiceover_path=wav, subtitle_text=_SUBTITLE, out_path=out
    )

    assert written == out
    assert out.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")

    manifest = json.loads(manifest_path(out).read_text(encoding="utf-8"))
    assert manifest["broll"] == str(broll)
    assert manifest["voiceover"] == str(wav)
    assert manifest["subtitles"] == _SUBTITLE
    assert manifest["engine"] == "mock-flick"


def test_missing_broll_raises(tmp_path: Path) -> None:
    _, wav = _inputs(tmp_path)
    with pytest.raises(VideoAssemblyError):
        MockFlickBuilder().build(
            broll_path=tmp_path / "nu_exista.mp4",
            voiceover_path=wav,
            subtitle_text=_SUBTITLE,
            out_path=tmp_path / "ad.mp4",
        )


def test_missing_voiceover_raises(tmp_path: Path) -> None:
    broll, _ = _inputs(tmp_path)
    with pytest.raises(VideoAssemblyError):
        MockFlickBuilder().build(
            broll_path=broll,
            voiceover_path=tmp_path / "nu_exista.wav",
            subtitle_text=_SUBTITLE,
            out_path=tmp_path / "ad.mp4",
        )


def test_empty_subtitle_raises(tmp_path: Path) -> None:
    broll, wav = _inputs(tmp_path)
    with pytest.raises(VideoAssemblyError):
        MockFlickBuilder().build(
            broll_path=broll,
            voiceover_path=wav,
            subtitle_text="  ",
            out_path=tmp_path / "ad.mp4",
        )


def test_live_builder_raises_setup_required(tmp_path: Path) -> None:
    broll, wav = _inputs(tmp_path)
    with pytest.raises(SetupRequiredError):
        FlickVideoBuilder().build(
            broll_path=broll,
            voiceover_path=wav,
            subtitle_text=_SUBTITLE,
            out_path=tmp_path / "ad.mp4",
        )
