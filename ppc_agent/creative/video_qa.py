"""Validare determinista a storyboard-urilor generate de LLM, inainte de salvare.

``StoryboardValidator`` nu depinde de niciun LLM - toate regulile sunt calcule
simple pe campuri numerice/text. Un storyboard care nu trece validarea nu se
salveaza niciodata: :meth:`StoryboardValidator.validate` ridica
:class:`~ppc_agent.errors.StoryboardValidationError` cu TOATE problemele
gasite (nu doar prima), ca un singur mesaj sa acopere tot ce trebuie corectat.
"""

from __future__ import annotations

from itertools import pairwise

from ppc_agent.creative.video_models import Storyboard
from ppc_agent.errors import StoryboardValidationError

_MAX_DURATION_SECONDS = 30.0
_CAPTION_MIN_CHARS = 24
_CAPTION_MAX_CHARS = 32
_CAPTION_MIN_DURATION = 0.9
_CTA_WINDOW_START = 3.0  # secunde inainte de finalul video-ului
_CTA_WINDOW_END = 6.0
_CTA_MIN_VISIBLE_DURATION = 2.0

# Zone de excludere UI, ca fractiune din inaltime/latime - vezi
# VideoCanvas.safe_zone_profile. Documentate aici (nu doar in prompt) ca sa
# poata fi verificate programatic daca schema TextOverlay capata vreodata
# coordonate explicite in loc de ancore predefinite.
SAFE_ZONE_EXCLUSIONS: dict[str, dict[str, float]] = {
    "tiktok_9x16": {"top": 0.14, "bottom": 0.35, "sides": 0.10},
}


class StoryboardValidator:
    """Verifica un :class:`Storyboard` fata de regulile deterministe de productie."""

    def validate(self, storyboard: Storyboard) -> None:
        """Ridica :class:`StoryboardValidationError` daca o regula e incalcata.

        Colecteaza toate problemele (timeline, ritm, tipografie, CTA) inainte
        de a ridica, in loc sa se opreasca la prima gasita.
        """
        issues: list[str] = [
            *self._check_pacing(storyboard),
            *self._check_timeline(storyboard),
            *self._check_typography(storyboard),
            *self._check_cta(storyboard),
        ]
        if issues:
            raise StoryboardValidationError(issues)

    def _check_pacing(self, storyboard: Storyboard) -> list[str]:
        if storyboard.duration_seconds > _MAX_DURATION_SECONDS:
            return [
                f"duration_seconds ({storyboard.duration_seconds}s) depaseste "
                f"limita de {_MAX_DURATION_SECONDS}s"
            ]
        return []

    def _check_timeline(self, storyboard: Storyboard) -> list[str]:
        issues: list[str] = []
        scenes = sorted(storyboard.scenes, key=lambda scene: scene.start_time)
        for scene in scenes:
            if scene.end_time <= scene.start_time:
                issues.append(
                    f"scena '{scene.id}': end_time ({scene.end_time}) trebuie sa fie "
                    f"> start_time ({scene.start_time})"
                )
        for previous, current in pairwise(scenes):
            if current.start_time > previous.end_time:
                issues.append(
                    f"gol neasteptat in timeline intre scena '{previous.id}' "
                    f"(sfarsit {previous.end_time}) si '{current.id}' "
                    f"(inceput {current.start_time})"
                )
        return issues

    def _check_typography(self, storyboard: Storyboard) -> list[str]:
        issues: list[str] = []
        for scene in storyboard.scenes:
            for overlay in scene.text_layers:
                if overlay.type != "caption":
                    continue
                length = len(overlay.text)
                if not (_CAPTION_MIN_CHARS <= length <= _CAPTION_MAX_CHARS):
                    issues.append(
                        f"scena '{scene.id}': caption '{overlay.text}' are {length} "
                        f"caractere, tinta e {_CAPTION_MIN_CHARS}-{_CAPTION_MAX_CHARS}"
                    )
                if overlay.duration < _CAPTION_MIN_DURATION:
                    issues.append(
                        f"scena '{scene.id}': caption '{overlay.text}' dureaza "
                        f"{overlay.duration}s, sub minimul de {_CAPTION_MIN_DURATION}s"
                    )
        return issues

    def _check_cta(self, storyboard: Storyboard) -> list[str]:
        cta_overlays = [
            overlay
            for scene in storyboard.scenes
            for overlay in scene.text_layers
            if overlay.type == "cta"
        ]
        if not cta_overlays:
            return ["niciun text de tip 'cta' gasit in storyboard"]

        total = storyboard.duration_seconds
        window_start = total - _CTA_WINDOW_END
        window_end = total - _CTA_WINDOW_START
        in_window = [
            overlay
            for overlay in cta_overlays
            if overlay.start_time <= window_end and overlay.end_time >= window_start
        ]

        issues: list[str] = []
        if not in_window:
            issues.append(
                f"niciun CTA vizibil in fereastra {window_start:.1f}s-{window_end:.1f}s "
                f"(ultimele {_CTA_WINDOW_START:.0f}-{_CTA_WINDOW_END:.0f}s din video)"
            )
        for overlay in in_window:
            if overlay.duration < _CTA_MIN_VISIBLE_DURATION:
                issues.append(
                    f"CTA '{overlay.text}' vizibil doar {overlay.duration}s, sub "
                    f"minimul de {_CTA_MIN_VISIBLE_DURATION}s"
                )
        return issues
