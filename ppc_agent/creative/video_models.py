"""Schema unui storyboard video programatic (regie de creatie, nu doar text).

Formatul master presupune un canvas 1080x1920, 30fps, 9:16 - potrivit pentru
video scurt vertical (TikTok, Reels, Shorts). Generat de LLM ca JSON strict
(vezi :func:`ppc_agent.copywriter.engine.build_storyboard_system_prompt`),
validat determinist de :class:`~ppc_agent.creative.video_qa.StoryboardValidator`
inainte de a fi salvat.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AnchorPosition = Literal[
    "safe_center", "top_center", "bottom_center", "center_left", "center_right"
]
OverlayType = Literal["caption", "headline", "cta"]
ContrastMode = Literal["adaptive_backplate", "solid_backplate", "none"]
AudioType = Literal["voiceover", "sfx", "music"]
ScenePurpose = Literal["hook", "problem", "proof", "cta", "body"]


class VideoCanvas(BaseModel):
    """Dimensiunile si profilul de zone sigure ale canvas-ului video.

    ``safe_zone_profile`` e ``str`` (nu ``Literal``) in mod deliberat: azi
    exista un singur profil (``"tiktok_9x16"``), dar un profil nou (ex. pentru
    Reels 4:5) nu trebuie sa ceara modificarea unui tip - doar inregistrarea
    lui in ``ppc_agent.creative.video_qa._SAFE_ZONE_PROFILES``.
    """

    width: int = 1080
    height: int = 1920
    fps: int = 30
    safe_zone_profile: str = "tiktok_9x16"


class TextOverlay(BaseModel):
    """Un element de text suprapus pe video (caption, headline sau CTA)."""

    type: OverlayType
    text: str
    start_time: float
    duration: float
    anchor_position: AnchorPosition = "safe_center"
    highlight_words: list[str] = Field(default_factory=list)
    contrast_mode: ContrastMode = "adaptive_backplate"

    @property
    def end_time(self) -> float:
        """Momentul la care overlay-ul dispare (``start_time + duration``)."""
        return self.start_time + self.duration


class AudioTrack(BaseModel):
    """O piesa audio (voce sau efect sonor) dintr-o scena."""

    type: AudioType
    asset_ref: str
    start_time: float
    volume: float = 1.0


class Scene(BaseModel):
    """O scena a storyboard-ului: interval de timp, b-roll, text si audio."""

    id: str
    start_time: float
    end_time: float
    purpose: ScenePurpose
    visual_broll_prompt: str
    text_layers: list[TextOverlay] = Field(default_factory=list)
    audio: list[AudioTrack] = Field(default_factory=list)


class Storyboard(BaseModel):
    """Storyboard-ul complet, generat de LLM si validat de ``StoryboardValidator``."""

    job_id: str
    duration_seconds: float
    canvas: VideoCanvas = Field(default_factory=VideoCanvas)
    scenes: list[Scene] = Field(default_factory=list)
