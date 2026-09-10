"""Teste pentru integrarea Fish Speech (TTS) — mock, offline."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from ppc_agent.creative.audio_engine import (
    FishSpeechClient,
    MockFishSpeechClient,
    estimate_duration_seconds,
)
from ppc_agent.errors import SetupRequiredError, TtsError

_SCRIPT = "Simti smucituri in cutia auto? O reparatie costa mai putin decat o cutie noua."


def test_mock_writes_a_valid_wav(tmp_path: Path) -> None:
    out = tmp_path / "voce" / "vo.wav"
    written = MockFishSpeechClient().synthesize(_SCRIPT, out)

    assert written == out
    assert out.is_file()
    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22_050
        assert wav.getnframes() > 0


def test_wav_duration_matches_estimate(tmp_path: Path) -> None:
    out = tmp_path / "vo.wav"
    MockFishSpeechClient().synthesize(_SCRIPT, out)
    with wave.open(str(out), "rb") as wav:
        actual_seconds = wav.getnframes() / wav.getframerate()
    assert actual_seconds == pytest.approx(estimate_duration_seconds(_SCRIPT), abs=0.1)


def test_empty_script_raises(tmp_path: Path) -> None:
    with pytest.raises(TtsError):
        MockFishSpeechClient().synthesize("   ", tmp_path / "vo.wav")


def test_estimate_duration_scales_and_has_floor() -> None:
    assert estimate_duration_seconds("un cuvant") >= 1.0
    short = estimate_duration_seconds("doua cuvinte aici")
    longer = estimate_duration_seconds("un script mult mai lung " * 20)
    assert longer > short


def test_mock_voice_is_configurable() -> None:
    assert MockFishSpeechClient(voice="ro_female").voice == "ro_female"


def test_live_client_raises_setup_required(tmp_path: Path) -> None:
    with pytest.raises(SetupRequiredError):
        FishSpeechClient().synthesize(_SCRIPT, tmp_path / "vo.wav")
