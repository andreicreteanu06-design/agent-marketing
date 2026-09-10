"""Teste pentru orchestratorul Modulului 5 si comanda CLI ``build-creative``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.config import AppConfig, ProviderMode, Settings
from ppc_agent.copywriter.llm import BaseLLMClient, LiveLLMClient, MockLLMClient
from ppc_agent.copywriter.models import AdCopy, CopySpec
from ppc_agent.creative.audio_engine import FishSpeechClient, MockFishSpeechClient
from ppc_agent.creative.creative_pipeline import (
    build_vo_script,
    generate_full_ad_creative,
)
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.creative.video_engine import FlickVideoBuilder, MockFlickBuilder
from ppc_agent.errors import VideoAssemblyError

runner = CliRunner()


def _broll(tmp_path: Path) -> Path:
    path = tmp_path / "broll.mp4"
    path.write_bytes(b"fake broll bytes")
    return path


def test_full_chain_produces_wav_and_mp4(tmp_path: Path) -> None:
    result = generate_full_ad_creative(
        MockLLMClient(),
        MockFishSpeechClient(),
        MockFlickBuilder(),
        keyword="revizie cutie automata",
        raw_broll_path=_broll(tmp_path),
        emotion_trigger="frica",
        product_usp="Golire completa cu Launch CAT-501S, ulei si filtru inclus",
        output_dir=tmp_path / "out",
    )

    assert Path(result.voiceover_path).is_file()
    assert Path(result.mp4_path).is_file()
    assert result.mp4_path.endswith(".mp4")
    assert result.framework_style == "pas"
    assert "revizie cutie automata" in result.script.lower()
    assert result.duration_seconds > 0
    assert result.manifest["llm_client"] == "MockLLMClient"
    assert result.manifest["tts_engine"] == "mock-fish-speech"
    assert result.manifest["video_engine"] == "mock-flick"


class _SpyLLM(BaseLLMClient):
    """Client de test care contorizeaza apelurile — dovada ca DI functioneaza."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, spec: CopySpec) -> AdCopy:
        self.calls += 1
        return AdCopy(
            headline_1=spec.target_keyword,
            headline_2="Nu ignora primele semne",
            description="Vino azi la o verificare rapida si evita costuri mari.",
        )


def test_llm_client_is_injected_not_hardcoded(tmp_path: Path) -> None:
    spy = _SpyLLM()
    result = generate_full_ad_creative(
        spy,
        MockFishSpeechClient(),
        MockFlickBuilder(),
        keyword="frana uzata",
        raw_broll_path=_broll(tmp_path),
        emotion_trigger="frica",
        output_dir=tmp_path / "out",
    )
    assert spy.calls == 1
    assert result.manifest["llm_client"] == "_SpyLLM"
    assert "frana uzata" in result.ad_copy.headline_1.lower()


def test_missing_broll_raises(tmp_path: Path) -> None:
    with pytest.raises(VideoAssemblyError):
        generate_full_ad_creative(
            MockLLMClient(),
            MockFishSpeechClient(),
            MockFlickBuilder(),
            keyword="test",
            raw_broll_path=tmp_path / "nu_exista.mp4",
            output_dir=tmp_path / "out",
        )


def test_build_vo_script_keeps_terminal_punctuation() -> None:
    script = build_vo_script(
        AdCopy(headline_1="Smucituri?", headline_2="Nu ignora", description="Vino azi")
    )
    assert script == "Smucituri? Nu ignora. Vino azi."


def test_creative_factory_switches_on_mode() -> None:
    mock_cfg = AppConfig(settings=Settings(_env_file=None, provider_mode=ProviderMode.MOCK))
    live_cfg = AppConfig(settings=Settings(_env_file=None, provider_mode=ProviderMode.LIVE))

    assert isinstance(CreativeFactory(mock_cfg).llm(), MockLLMClient)
    assert isinstance(CreativeFactory(mock_cfg).tts(), MockFishSpeechClient)
    assert isinstance(CreativeFactory(mock_cfg).video(), MockFlickBuilder)
    assert isinstance(CreativeFactory(live_cfg).llm(), LiveLLMClient)
    assert isinstance(CreativeFactory(live_cfg).tts(), FishSpeechClient)
    assert isinstance(CreativeFactory(live_cfg).video(), FlickVideoBuilder)


def test_cli_build_creative_outputs_mp4_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    broll = _broll(tmp_path)
    result = runner.invoke(
        app,
        [
            "build-creative",
            "--keyword",
            "curs excel",
            "--broll",
            str(broll),
            "--trigger",
            "fomo",
        ],
    )
    assert result.exit_code == 0
    assert ".mp4" in result.output

    produced = list((tmp_path / "creative_output").glob("*.mp4"))
    assert len(produced) == 1
    assert produced[0].read_bytes().startswith(b"\x00\x00\x00\x18ftyp")


def test_cli_build_creative_missing_broll_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["build-creative", "--keyword", "x", "--broll", "nu_exista.mp4"]
    )
    assert result.exit_code == 1
