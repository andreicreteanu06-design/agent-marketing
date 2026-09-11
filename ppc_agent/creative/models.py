"""Structuri de date tipizate pentru Modulul 5 (creatii audio/video)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ppc_agent.copywriter.models import AdCopy, FrameworkStyle, TikTokAdCopy


class VoiceoverResult(BaseModel):
    """Rezultatul sintezei vocale (Fish Speech)."""

    script: str
    wav_path: str
    duration_seconds: float
    voice: str
    engine: str


class CreativeResult(BaseModel):
    """Anuntul video finalizat, plus tot lantul care l-a produs.

    ``platform`` disambiguizeaza care dintre ``framework_style`` (Google, RAG pe
    declansator emotional) sau ``creative_angle`` (TikTok, RAG pe nisa/cuvant cheie)
    e populat — celalalt ramane ``None``.
    """

    created_at: datetime
    platform: Literal["google", "tiktok"] = "google"
    keyword: str
    emotion_trigger: str
    framework_style: FrameworkStyle | None = None
    creative_angle: str | None = None
    product_usp: str
    ad_copy: AdCopy | TikTokAdCopy
    script: str
    subtitle_text: str
    broll_path: str
    voiceover_path: str
    mp4_path: str
    duration_seconds: float
    manifest: dict[str, str] = Field(default_factory=dict)
