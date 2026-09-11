"""Teste deterministe pentru generarea de copy omnicanal (Google/Meta/TikTok)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.copywriter.engine import AdCopyGenerator, build_omnichannel_system_prompt
from ppc_agent.copywriter.llm import BaseLLMClient, MockLLMClient
from ppc_agent.copywriter.models import AdCopy, CopySpec, OmniSwipeRecord, SwipeFile
from ppc_agent.copywriter.swipe import default_swipe_path, load_swipe_file
from ppc_agent.errors import SwipeFileError

_USP = "Diagnoza in 30 de minute, pret fix, verdict clar pe loc"

_OMNI_KEYS = {
    "hook_type",
    "hook_text",
    "problem_agitation",
    "mechanism_proof",
    "offer_cta",
}


class _BareLLM(BaseLLMClient):
    """Client minimal care implementeaza doar metoda abstracta ``generate``."""

    def generate(self, spec: CopySpec) -> AdCopy:
        raise AssertionError("nu ar trebui apelat in acest test")


def _generator() -> AdCopyGenerator:
    return AdCopyGenerator(MockLLMClient())


def test_base_client_generate_omnichannel_raises_not_implemented() -> None:
    """Clientii de test existenti (doar `generate`) raman instantiabili nemodificati."""
    client = _BareLLM()
    with pytest.raises(NotImplementedError):
        client.generate_omnichannel(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("target_platform", ["google", "meta", "tiktok"])
def test_omnichannel_copy_has_all_fields(target_platform: str) -> None:
    result = _generator().generate_omnichannel_copy(
        _USP, "cutie de viteze auto", target_platform  # type: ignore[arg-type]
    )
    assert set(result) == _OMNI_KEYS
    assert all(isinstance(value, str) and value for value in result.values())


def test_omnichannel_generation_is_deterministic() -> None:
    first = _generator().generate_omnichannel_copy(_USP, "bratara argint", "meta")
    second = _generator().generate_omnichannel_copy(_USP, "bratara argint", "meta")
    assert first == second


def test_omnichannel_retrieval_filters_by_platform() -> None:
    """Cererea pentru 'google' nu poate returna un exemplu marcat 'tiktok'."""
    google_result = _generator().generate_omnichannel_copy(
        _USP, "reparatii auto revizie", "google"
    )
    tiktok_result = _generator().generate_omnichannel_copy(
        _USP, "reparatii auto revizie", "tiktok"
    )
    # Ambele nise se suprapun (revizie auto), dar exemplele-ancora difera pe
    # platforma - rezultatele MockLLMClient (compuse din exemplul recuperat)
    # trebuie sa difere intre cele doua platforme.
    assert google_result != tiktok_result


def test_empty_omnichannel_platform_raises_swipe_file_error(tmp_path: Path) -> None:
    bare = load_swipe_file(default_swipe_path())
    only_google = SwipeFile(
        frameworks=bare.frameworks,
        omnichannel_swipe_library=[
            OmniSwipeRecord(
                ad_id="g1",
                platform="google",
                niche="orice",
                format="search_text",
                performance_signal="active",
                hook_type="hook_type",
                hook_text="hook",
                problem_agitation="problema",
                mechanism_proof="dovada",
                offer_cta="cta",
            )
        ],
    )
    path = tmp_path / "swipe_file.json"
    path.write_text(only_google.model_dump_json(), encoding="utf-8")

    generator = AdCopyGenerator(MockLLMClient(), swipe_path=path)
    with pytest.raises(SwipeFileError):
        generator.generate_omnichannel_copy(_USP, "orice", "meta")


def test_google_and_tiktok_legacy_paths_are_unaffected() -> None:
    """generate_emotional_copy (platform="google"/"tiktok") ramane 100% neschimbat."""
    generator = _generator()
    google = generator.generate_emotional_copy(_USP, "curs excel", "aida")
    assert set(google) == {"headline_1", "headline_2", "description"}
    tiktok = generator.generate_emotional_copy(
        _USP, "cutie de viteze", "frica", platform="tiktok"
    )
    assert set(tiktok) == {
        "visual_hook_concept",
        "audio_hook",
        "body_script",
        "text_overlay",
        "call_to_action",
        "creative_angle",
    }


def test_build_omnichannel_system_prompt_varies_by_platform() -> None:
    examples: list[OmniSwipeRecord] = []
    google_prompt = build_omnichannel_system_prompt("google", examples)
    meta_prompt = build_omnichannel_system_prompt("meta", examples)
    tiktok_prompt = build_omnichannel_system_prompt("tiktok", examples)

    assert "Search" in google_prompt
    assert "advertorial" in meta_prompt
    assert "3 secunde" in tiktok_prompt
    assert google_prompt != meta_prompt != tiktok_prompt


def test_build_omnichannel_system_prompt_includes_examples() -> None:
    example = OmniSwipeRecord(
        ad_id="t1",
        platform="tiktok",
        niche="test niche",
        format="ugc_video",
        longevity_days=30,
        variation_count=4,
        performance_signal="active_30_days",
        hook_type="pattern_interrupt",
        hook_text="hook de test",
        problem_agitation="problema de test",
        mechanism_proof="dovada de test",
        offer_cta="cta de test",
    )
    prompt = build_omnichannel_system_prompt("tiktok", [example])
    assert "hook de test" in prompt
    assert "hook_type" in prompt
    assert "offer_cta" in prompt


def test_build_omnichannel_system_prompt_handles_no_examples() -> None:
    prompt = build_omnichannel_system_prompt("google", [])
    assert "improvizeaza" in prompt
