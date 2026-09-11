"""Teste deterministe pentru generarea de storyboard-uri (Lead Creative Director)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.copywriter.engine import AdCopyGenerator, build_storyboard_system_prompt
from ppc_agent.copywriter.llm import BaseLLMClient, MockLLMClient
from ppc_agent.copywriter.models import AdCopy, CopySpec, SwipeFile
from ppc_agent.copywriter.swipe import default_swipe_path, load_swipe_file
from ppc_agent.creative.video_qa import StoryboardValidator
from ppc_agent.errors import SwipeFileError

_USP = "Diagnoza in 30 de minute, pret fix, verdict clar pe loc"


class _BareLLM(BaseLLMClient):
    """Client minimal care implementeaza doar metoda abstracta ``generate``."""

    def generate(self, spec: CopySpec) -> AdCopy:
        raise AssertionError("nu ar trebui apelat in acest test")


def _generator() -> AdCopyGenerator:
    return AdCopyGenerator(MockLLMClient())


def test_base_client_generate_storyboard_raises_not_implemented() -> None:
    client = _BareLLM()
    with pytest.raises(NotImplementedError):
        client.generate_storyboard(None)  # type: ignore[arg-type]


def test_mock_storyboard_passes_the_validator() -> None:
    """Storyboard-ul MockLLMClient trebuie sa respecte propriile reguli prin design."""
    storyboard = _generator().generate_storyboard(_USP, "cutie de viteze auto")
    StoryboardValidator().validate(storyboard)  # nu ridica


def test_storyboard_has_hook_and_cta_scenes() -> None:
    storyboard = _generator().generate_storyboard(_USP, "cutie de viteze")
    purposes = [scene.purpose for scene in storyboard.scenes]
    assert "hook" in purposes
    assert "cta" in purposes
    assert storyboard.scenes[0].purpose == "hook"
    assert storyboard.scenes[0].start_time == 0.0


def test_storyboard_generation_is_deterministic() -> None:
    first = _generator().generate_storyboard(_USP, "bratara argint")
    second = _generator().generate_storyboard(_USP, "bratara argint")
    assert first == second


def test_storyboard_uses_niche_rag_like_tiktok_path() -> None:
    """Recuperarea foloseste tiktok_swipe_library - un exemplu de nisa auto ancoreaza hook-ul."""
    storyboard = _generator().generate_storyboard(_USP, "cutie de viteze auto")
    hook_scene = next(scene for scene in storyboard.scenes if scene.purpose == "hook")
    headline = hook_scene.text_layers[0].text
    assert headline  # ancorat din swipe library, nu gol/generic


def test_empty_tiktok_library_raises_swipe_file_error(tmp_path: Path) -> None:
    bare = load_swipe_file(default_swipe_path())
    empty = SwipeFile(frameworks=bare.frameworks, tiktok_swipe_library=[])
    path = tmp_path / "swipe_file.json"
    path.write_text(empty.model_dump_json(), encoding="utf-8")

    generator = AdCopyGenerator(MockLLMClient(), swipe_path=path)
    with pytest.raises(SwipeFileError):
        generator.generate_storyboard(_USP, "orice")


def test_build_storyboard_system_prompt_includes_art_director_rules() -> None:
    prompt = build_storyboard_system_prompt([])
    assert "1.5-3.0" in prompt
    assert "B-roll" in prompt
    assert "safe_center" in prompt
    assert "adaptive_backplate" in prompt
    assert "karaoke" in prompt
    assert "2.5" in prompt


def test_build_storyboard_system_prompt_embeds_real_schema_example() -> None:
    prompt = build_storyboard_system_prompt([])
    assert '"job_id"' in prompt
    assert '"scenes"' in prompt
    assert '"text_layers"' in prompt


def test_build_storyboard_system_prompt_includes_examples() -> None:
    swipe = load_swipe_file(default_swipe_path())
    prompt = build_storyboard_system_prompt(swipe.tiktok_swipe_library[:1])
    assert swipe.tiktok_swipe_library[0].hook_audio in prompt
