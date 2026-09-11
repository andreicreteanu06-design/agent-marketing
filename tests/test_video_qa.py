"""Teste pentru StoryboardValidator (regulile deterministe de productie video)."""

from __future__ import annotations

import pytest

from ppc_agent.copywriter.prompts import STORYBOARD_FORMAT_EXAMPLE
from ppc_agent.creative.video_models import Scene, Storyboard, TextOverlay
from ppc_agent.creative.video_qa import StoryboardValidator
from ppc_agent.errors import StoryboardValidationError

_VALID_CAPTION = "Rezultatul se vede din prima zi"  # 31 caractere


def _cta_overlay(*, start_time: float, duration: float, text: str = "Comanda acum") -> TextOverlay:
    return TextOverlay(type="cta", text=text, start_time=start_time, duration=duration)


def _storyboard(
    *, duration_seconds: float = 22.0, scenes: list[Scene] | None = None
) -> Storyboard:
    default_scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=16.0,
            purpose="hook",
            visual_broll_prompt="zoom",
        ),
        Scene(
            id="s2",
            start_time=16.0,
            end_time=duration_seconds,
            purpose="cta",
            visual_broll_prompt="produs in cadru",
            text_layers=[
                _cta_overlay(start_time=duration_seconds - 5, duration=5.0)
            ],
        ),
    ]
    return Storyboard(
        job_id="test",
        duration_seconds=duration_seconds,
        scenes=scenes if scenes is not None else default_scenes,
    )


def test_example_storyboard_passes_validation() -> None:
    StoryboardValidator().validate(STORYBOARD_FORMAT_EXAMPLE)  # nu ridica


def test_pacing_rule_rejects_over_30_seconds() -> None:
    storyboard = _storyboard(duration_seconds=31.0)
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(storyboard)
    assert any("duration_seconds" in issue for issue in exc_info.value.issues)


def test_pacing_rule_accepts_exactly_30_seconds() -> None:
    StoryboardValidator().validate(_storyboard(duration_seconds=30.0))


def test_timeline_rule_rejects_end_before_start() -> None:
    scenes = [
        Scene(id="s1", start_time=5.0, end_time=3.0, purpose="hook", visual_broll_prompt="x"),
        Scene(
            id="s2",
            start_time=3.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("end_time" in issue and "s1" in issue for issue in exc_info.value.issues)


def test_timeline_rule_rejects_unexpected_gap() -> None:
    scenes = [
        Scene(id="s1", start_time=0.0, end_time=5.0, purpose="hook", visual_broll_prompt="x"),
        Scene(
            id="s2",
            start_time=8.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("gol neasteptat" in issue for issue in exc_info.value.issues)


def test_timeline_rule_allows_touching_scenes_with_no_gap() -> None:
    scenes = [
        Scene(id="s1", start_time=0.0, end_time=5.0, purpose="hook", visual_broll_prompt="x"),
        Scene(
            id="s2",
            start_time=5.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    StoryboardValidator().validate(_storyboard(scenes=scenes))  # nu ridica


def test_typography_rule_rejects_caption_too_short() -> None:
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=16.0,
            purpose="hook",
            visual_broll_prompt="x",
            text_layers=[
                TextOverlay(type="caption", text="prea scurt", start_time=0.0, duration=1.5)
            ],
        ),
        Scene(
            id="s2",
            start_time=16.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("caractere" in issue for issue in exc_info.value.issues)


def test_typography_rule_rejects_caption_too_long() -> None:
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=16.0,
            purpose="hook",
            visual_broll_prompt="x",
            text_layers=[
                TextOverlay(
                    type="caption",
                    text="Un caption mult prea lung ca sa incapa in fereastra ceruta",
                    start_time=0.0,
                    duration=1.5,
                )
            ],
        ),
        Scene(
            id="s2",
            start_time=16.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("caractere" in issue for issue in exc_info.value.issues)


def test_typography_rule_rejects_caption_duration_below_minimum() -> None:
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=16.0,
            purpose="hook",
            visual_broll_prompt="x",
            text_layers=[
                TextOverlay(type="caption", text=_VALID_CAPTION, start_time=0.0, duration=0.5)
            ],
        ),
        Scene(
            id="s2",
            start_time=16.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("dureaza" in issue for issue in exc_info.value.issues)


def test_typography_rule_ignores_headline_and_cta_length() -> None:
    """Regula de 24-32 caractere se aplica DOAR caption-urilor, nu headline/cta."""
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=16.0,
            purpose="hook",
            visual_broll_prompt="x",
            text_layers=[TextOverlay(type="headline", text="scurt", start_time=0.0, duration=1.5)],
        ),
        Scene(
            id="s2",
            start_time=16.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=17.0, duration=5.0, text="scurt")],
        ),
    ]
    StoryboardValidator().validate(_storyboard(scenes=scenes))  # nu ridica


def test_cta_rule_rejects_missing_cta() -> None:
    scenes = [
        Scene(id="s1", start_time=0.0, end_time=22.0, purpose="hook", visual_broll_prompt="x"),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("niciun text de tip 'cta'" in issue for issue in exc_info.value.issues)


def test_cta_rule_rejects_cta_outside_window() -> None:
    """CTA plasat prea devreme (la 5s dintr-un video de 22s) nu atinge fereastra finala."""
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=22.0,
            purpose="hook",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=5.0, duration=2.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("fereastra" in issue for issue in exc_info.value.issues)


def test_cta_rule_rejects_cta_shorter_than_minimum_visible_duration() -> None:
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=18.0, duration=1.0)],
        ),
    ]
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(_storyboard(scenes=scenes))
    assert any("vizibil doar" in issue for issue in exc_info.value.issues)


def test_cta_rule_accepts_cta_overlapping_window_even_if_it_starts_earlier() -> None:
    """CTA care incepe la 15s si tine 7s (pana la final, 22s) acopera fereastra 16-19s."""
    scenes = [
        Scene(
            id="s1",
            start_time=0.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="x",
            text_layers=[_cta_overlay(start_time=15.0, duration=7.0)],
        ),
    ]
    StoryboardValidator().validate(_storyboard(scenes=scenes))  # nu ridica


def test_validator_collects_all_issues_not_just_first() -> None:
    scenes = [
        Scene(id="s1", start_time=5.0, end_time=3.0, purpose="hook", visual_broll_prompt="x"),
    ]
    storyboard = _storyboard(duration_seconds=99.0, scenes=scenes)
    with pytest.raises(StoryboardValidationError) as exc_info:
        StoryboardValidator().validate(storyboard)
    issues = exc_info.value.issues
    assert len(issues) >= 3  # pacing + timeline (end<start) + cta lipsa
    assert any("duration_seconds" in issue for issue in issues)
    assert any("end_time" in issue for issue in issues)
    assert any("cta" in issue for issue in issues)
