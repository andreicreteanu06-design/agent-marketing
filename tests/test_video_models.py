"""Teste pentru schema storyboard-ului programatic (Pydantic, fara logica)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ppc_agent.creative.video_models import (
    AudioTrack,
    Scene,
    Storyboard,
    TextOverlay,
    VideoCanvas,
)


def test_video_canvas_defaults_match_master_format() -> None:
    canvas = VideoCanvas()
    assert (canvas.width, canvas.height, canvas.fps) == (1080, 1920, 30)
    assert canvas.safe_zone_profile == "tiktok_9x16"


def test_text_overlay_end_time_is_start_plus_duration() -> None:
    overlay = TextOverlay(type="caption", text="x" * 24, start_time=2.0, duration=1.5)
    assert overlay.end_time == 3.5


def test_text_overlay_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        TextOverlay(type="subtitle", text="x", start_time=0.0, duration=1.0)  # type: ignore[arg-type]


def test_text_overlay_rejects_unknown_anchor() -> None:
    with pytest.raises(ValidationError):
        TextOverlay(
            type="cta",
            text="x",
            start_time=0.0,
            duration=1.0,
            anchor_position="top_edge",  # type: ignore[arg-type]
        )


def test_text_overlay_defaults() -> None:
    overlay = TextOverlay(type="headline", text="x", start_time=0.0, duration=1.0)
    assert overlay.anchor_position == "safe_center"
    assert overlay.contrast_mode == "adaptive_backplate"
    assert overlay.highlight_words == []


def test_audio_track_default_volume() -> None:
    track = AudioTrack(type="voiceover", asset_ref="a.wav", start_time=0.0)
    assert track.volume == 1.0


def test_storyboard_defaults_to_empty_scenes_and_default_canvas() -> None:
    storyboard = Storyboard(job_id="j1", duration_seconds=10.0)
    assert storyboard.scenes == []
    assert storyboard.canvas == VideoCanvas()


def test_storyboard_round_trips_through_json() -> None:
    storyboard = Storyboard(
        job_id="j1",
        duration_seconds=10.0,
        scenes=[
            Scene(
                id="s1",
                start_time=0.0,
                end_time=10.0,
                purpose="hook",
                visual_broll_prompt="zoom",
                text_layers=[
                    TextOverlay(type="cta", text="x" * 24, start_time=0.0, duration=2.0)
                ],
                audio=[AudioTrack(type="voiceover", asset_ref="a.wav", start_time=0.0)],
            )
        ],
    )
    restored = Storyboard.model_validate_json(storyboard.model_dump_json())
    assert restored == storyboard
