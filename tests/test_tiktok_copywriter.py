"""Teste deterministe pentru generarea de copy TikTok (platform="tiktok")."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.copywriter.engine import AdCopyGenerator, build_tiktok_system_prompt
from ppc_agent.copywriter.llm import MockLLMClient
from ppc_agent.copywriter.models import SwipeFile, TikTokSwipeRecord
from ppc_agent.copywriter.swipe import default_swipe_path, load_swipe_file
from ppc_agent.errors import SwipeFileError

_USP = "Diagnoza in 30 de minute, pret fix, verdict clar pe loc"

_TIKTOK_KEYS = {
    "visual_hook_concept",
    "audio_hook",
    "body_script",
    "text_overlay",
    "call_to_action",
    "creative_angle",
}


def _generator() -> AdCopyGenerator:
    return AdCopyGenerator(MockLLMClient())


def test_tiktok_copy_has_all_fields_and_list_overlay() -> None:
    result = _generator().generate_emotional_copy(
        _USP, "cutie de viteze", "frica", platform="tiktok"
    )
    assert set(result) == _TIKTOK_KEYS
    assert isinstance(result["text_overlay"], list)
    assert all(isinstance(item, str) for item in result["text_overlay"])
    assert isinstance(result["creative_angle"], str) and result["creative_angle"]


def test_tiktok_generation_is_deterministic() -> None:
    first = _generator().generate_emotional_copy(
        _USP, "bratara argint", "status", platform="tiktok"
    )
    second = _generator().generate_emotional_copy(
        _USP, "bratara argint", "status", platform="tiktok"
    )
    assert first == second


def test_google_path_is_default_and_unaffected() -> None:
    """platform implicit ("google") produce tot forma veche (3 chei string)."""
    result = _generator().generate_emotional_copy(_USP, "curs excel", "aida")
    assert set(result) == {"headline_1", "headline_2", "description"}


def test_empty_tiktok_library_raises_swipe_file_error(tmp_path: Path) -> None:
    bare = load_swipe_file(default_swipe_path())
    empty = SwipeFile(frameworks=bare.frameworks, tiktok_swipe_library=[])
    path = tmp_path / "swipe_file.json"
    path.write_text(empty.model_dump_json(), encoding="utf-8")

    generator = AdCopyGenerator(MockLLMClient(), swipe_path=path)
    with pytest.raises(SwipeFileError):
        generator.generate_emotional_copy(_USP, "orice", "aida", platform="tiktok")


def test_build_tiktok_system_prompt_includes_examples_and_pacing() -> None:
    examples = [
        TikTokSwipeRecord(
            ad_id="t1",
            niche="test niche",
            format="test_format",
            days_active_proxy=30,
            hook_visual="zoom",
            hook_audio="hook de test",
            mechanism_proof="dovada de test",
            cta_text="cta de test",
        )
    ]
    prompt = build_tiktok_system_prompt(examples)
    assert "hook de test" in prompt
    assert "1.5-3" in prompt
    assert "15-30" in prompt
    assert "creative_angle" in prompt
    assert "text_overlay" in prompt


def test_build_tiktok_system_prompt_handles_no_examples() -> None:
    prompt = build_tiktok_system_prompt([])
    assert "improvizeaza" in prompt
