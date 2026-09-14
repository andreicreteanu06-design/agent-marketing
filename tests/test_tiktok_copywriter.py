"""Teste deterministe pentru generarea de copy TikTok (platform="tiktok")."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.copywriter.engine import (
    AdCopyGenerator,
    build_objective_guidance,
    build_tiktok_system_prompt,
)
from ppc_agent.copywriter.llm import BaseLLMClient, MockLLMClient
from ppc_agent.copywriter.models import (
    AdCopy,
    CopySpec,
    SwipeFile,
    TikTokAdCopy,
    TikTokCopySpec,
    TikTokSwipeRecord,
)
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


class _SpyTikTokClient(BaseLLMClient):
    """Client de test: captureaza spec-ul TikTok primit, fara sa-l foloseasca."""

    def __init__(self) -> None:
        self.last_spec: TikTokCopySpec | None = None

    def generate(self, spec: CopySpec) -> AdCopy:  # pragma: no cover - neexercitat aici
        raise NotImplementedError

    def generate_tiktok(self, spec: TikTokCopySpec) -> TikTokAdCopy:
        self.last_spec = spec
        return TikTokAdCopy(
            visual_hook_concept="x",
            audio_hook="x",
            body_script="x",
            text_overlay=["x"],
            call_to_action="x",
            creative_angle="x",
        )


def test_tiktok_generation_injects_objective_guidance_into_prompt() -> None:
    spy = _SpyTikTokClient()
    AdCopyGenerator(spy).generate_emotional_copy(
        _USP,
        "cutie de viteze",
        "frica",
        platform="tiktok",
        objective=CampaignObjective.LEAD_GEN,
    )
    assert spy.last_spec is not None
    assert build_objective_guidance(CampaignObjective.LEAD_GEN) in spy.last_spec.system_prompt
    assert "PRINCIPII DE PERSUASIUNE" in spy.last_spec.system_prompt
    assert "PAS" in spy.last_spec.system_prompt
