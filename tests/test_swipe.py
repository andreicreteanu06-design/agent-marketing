"""Teste pentru incarcarea si recuperarea din swipe_file.json (RAG local)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.copywriter.models import OmniSwipeRecord, SwipeFile, TikTokSwipeRecord
from ppc_agent.copywriter.swipe import (
    default_swipe_path,
    load_swipe_file,
    retrieve_framework,
    retrieve_omnichannel_examples,
    retrieve_tiktok_examples,
)
from ppc_agent.errors import SwipeFileError


def test_default_swipe_file_loads_and_has_four_styles() -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert set(swipe.styles()) == {"pas", "status", "fomo", "aida"}


def test_default_swipe_file_has_tiktok_library() -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert len(swipe.tiktok_swipe_library) >= 2
    niches = {record.niche for record in swipe.tiktok_swipe_library}
    assert any("auto" in niche for niche in niches)
    assert any("bijuterii" in niche for niche in niches)


def test_retrieve_tiktok_examples_matches_niche() -> None:
    swipe = load_swipe_file(default_swipe_path())
    top = retrieve_tiktok_examples(swipe, "cutie de viteze auto")
    assert top
    assert all("auto" in record.niche for record in top)


def test_retrieve_tiktok_examples_respects_limit() -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert len(retrieve_tiktok_examples(swipe, "bijuterii", limit=1)) == 1
    assert len(retrieve_tiktok_examples(swipe, "bijuterii", limit=3)) <= 3


def test_retrieve_tiktok_examples_prefers_longer_active_on_tie() -> None:
    swipe = SwipeFile(
        frameworks=load_swipe_file(default_swipe_path()).frameworks,
        tiktok_swipe_library=[
            TikTokSwipeRecord(
                ad_id="short",
                niche="zzz nisa fara suprapunere",
                format="x",
                days_active_proxy=5,
                hook_visual="v",
                hook_audio="a",
                mechanism_proof="m",
                cta_text="c",
            ),
            TikTokSwipeRecord(
                ad_id="long",
                niche="zzz nisa fara suprapunere",
                format="x",
                days_active_proxy=90,
                hook_visual="v",
                hook_audio="a",
                mechanism_proof="m",
                cta_text="c",
            ),
        ],
    )
    top = retrieve_tiktok_examples(swipe, "cuvant care nu se suprapune deloc", limit=1)
    assert top[0].ad_id == "long"


def test_retrieve_tiktok_examples_raises_on_empty_library() -> None:
    swipe = SwipeFile(
        frameworks=load_swipe_file(default_swipe_path()).frameworks,
        tiktok_swipe_library=[],
    )
    with pytest.raises(SwipeFileError):
        retrieve_tiktok_examples(swipe, "orice")


def test_default_swipe_file_has_omnichannel_library() -> None:
    swipe = load_swipe_file(default_swipe_path())
    assert len(swipe.omnichannel_swipe_library) >= 3
    platforms = {record.platform for record in swipe.omnichannel_swipe_library}
    assert platforms == {"google", "meta", "tiktok"}


def test_retrieve_omnichannel_examples_filters_by_platform() -> None:
    swipe = load_swipe_file(default_swipe_path())
    top = retrieve_omnichannel_examples(swipe, "google", "cutie de viteze")
    assert top
    assert all(record.platform == "google" for record in top)


def test_retrieve_omnichannel_examples_matches_niche() -> None:
    swipe = load_swipe_file(default_swipe_path())
    top = retrieve_omnichannel_examples(swipe, "meta", "bijuterii bratara argint")
    assert top
    assert "bijuterii" in top[0].niche


def test_retrieve_omnichannel_examples_respects_limit() -> None:
    swipe = SwipeFile(
        frameworks=load_swipe_file(default_swipe_path()).frameworks,
        omnichannel_swipe_library=[
            OmniSwipeRecord(
                ad_id=f"om_{i}",
                platform="tiktok",
                niche="nisa test",
                format="ugc_video",
                performance_signal="active",
                hook_type="pattern_interrupt",
                hook_text="hook",
                problem_agitation="problema",
                mechanism_proof="dovada",
                offer_cta="cta",
            )
            for i in range(3)
        ],
    )
    assert len(retrieve_omnichannel_examples(swipe, "tiktok", "nisa test", limit=1)) == 1
    assert len(retrieve_omnichannel_examples(swipe, "tiktok", "nisa test", limit=5)) == 3


def test_retrieve_omnichannel_examples_prefers_higher_longevity_on_tie() -> None:
    swipe = SwipeFile(
        frameworks=load_swipe_file(default_swipe_path()).frameworks,
        omnichannel_swipe_library=[
            OmniSwipeRecord(
                ad_id="short",
                platform="meta",
                niche="zzz nisa fara suprapunere",
                format="x",
                longevity_days=5,
                variation_count=1,
                performance_signal="active",
                hook_type="hook_type",
                hook_text="hook",
                problem_agitation="problema",
                mechanism_proof="dovada",
                offer_cta="cta",
            ),
            OmniSwipeRecord(
                ad_id="long",
                platform="meta",
                niche="zzz nisa fara suprapunere",
                format="x",
                longevity_days=90,
                variation_count=1,
                performance_signal="active",
                hook_type="hook_type",
                hook_text="hook",
                problem_agitation="problema",
                mechanism_proof="dovada",
                offer_cta="cta",
            ),
        ],
    )
    top = retrieve_omnichannel_examples(
        swipe, "meta", "cuvant care nu se suprapune deloc", limit=1
    )
    assert top[0].ad_id == "long"


def test_retrieve_omnichannel_examples_raises_when_platform_missing() -> None:
    swipe = SwipeFile(
        frameworks=load_swipe_file(default_swipe_path()).frameworks,
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
            ),
        ],
    )
    with pytest.raises(SwipeFileError):
        retrieve_omnichannel_examples(swipe, "meta", "orice")


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
