"""Structuri de date tipizate pentru Modulul 5 (creatii audio/video)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ppc_agent.copywriter.models import AdCopy, FrameworkStyle


class VoiceoverResult(BaseModel):
    """Rezultatul sintezei vocale (Fish Speech)."""

    script: str
    wav_path: str
    duration_seconds: float
    voice: str
    engine: str


class CreativeResult(BaseModel):
    """Anuntul video finalizat, plus tot lantul care l-a produs."""

    created_at: datetime
    keyword: str
    emotion_trigger: str
    framework_style: FrameworkStyle
    product_usp: str
    ad_copy: AdCopy
    script: str
    subtitle_text: str
    broll_path: str
    voiceover_path: str
    mp4_path: str
    duration_seconds: float
    manifest: dict[str, str] = Field(default_factory=dict)
