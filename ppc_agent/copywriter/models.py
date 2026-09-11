"""Structuri de date tipizate pentru modulul de copywriting."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FrameworkStyle = Literal["pas", "status", "fomo", "aida"]

HEADLINE_LIMIT = 30
DESCRIPTION_LIMIT = 90


def char_count(text: str) -> int:
    """Numarul de caractere dupa normalizare NFC (cum numara si Google Ads)."""
    return len(unicodedata.normalize("NFC", text))


class ExampleAd(BaseModel):
    """Un anunt-exemplu dintr-un framework (ilustreaza structura emotionala)."""

    headline_1: str
    headline_2: str
    description: str


class Framework(BaseModel):
    """O formula de direct-response din ``swipe_file.json``."""

    name: str
    style: FrameworkStyle
    trigger: str
    structure: str = ""
    example_ad: ExampleAd


class TikTokSwipeRecord(BaseModel):
    """O intrare din biblioteca proprie de anunturi TikTok cu performanta dovedita.

    ``days_active_proxy`` e un semnal indirect de performanta: platformele opresc
    rapid anunturile care nu merg, deci o reclama activa mult timp e, de regula,
    profitabila. Folosit ca tie-breaker la recuperarea RAG (vezi
    :func:`~ppc_agent.copywriter.swipe.retrieve_tiktok_examples`).
    """

    ad_id: str
    niche: str
    format: str
    days_active_proxy: int = 14
    hook_visual: str
    hook_audio: str
    mechanism_proof: str
    cta_text: str


class SwipeFile(BaseModel):
    """Continutul ``swipe_file.json``."""

    frameworks: list[Framework] = Field(min_length=1)
    tiktok_swipe_library: list[TikTokSwipeRecord] = Field(default_factory=list)

    def styles(self) -> list[str]:
        """Stilurile disponibile, in ordine."""
        return [framework.style for framework in self.frameworks]


class AdCopy(BaseModel):
    """Copy-ul final al unui anunt Google Ads."""

    headline_1: str
    headline_2: str
    description: str

    def as_dict(self) -> dict[str, str]:
        """Forma ceruta la iesire: ``{"headline_1", "headline_2", "description"}``."""
        return {
            "headline_1": self.headline_1,
            "headline_2": self.headline_2,
            "description": self.description,
        }


class TikTokAdCopy(BaseModel):
    """Copy-ul final al unui anunt TikTok (script video vertical, 9:16)."""

    visual_hook_concept: str
    audio_hook: str
    body_script: str
    text_overlay: list[str]
    call_to_action: str
    creative_angle: str

    def as_dict(self) -> dict[str, Any]:
        """Forma ceruta la iesire; spre deosebire de :class:`AdCopy`, nu e omogena
        (``text_overlay`` e o lista), deci foloseste tipul mai larg ``Any``."""
        return self.model_dump()


class CopySpec(BaseModel):
    """Tot ce ii trebuie unui :class:`~ppc_agent.copywriter.llm.BaseLLMClient` sa genereze."""

    product_usp: str
    target_keyword: str
    emotion_trigger: str
    framework: Framework
    system_prompt: str
    headline_limit: int = HEADLINE_LIMIT
    description_limit: int = DESCRIPTION_LIMIT
    tighten: int = 0


class TikTokCopySpec(BaseModel):
    """Tot ce ii trebuie unui :class:`~ppc_agent.copywriter.llm.BaseLLMClient` sa
    genereze un :class:`TikTokAdCopy`."""

    product_usp: str
    target_keyword: str
    emotion_trigger: str
    examples: list[TikTokSwipeRecord] = Field(default_factory=list)
    system_prompt: str


class QueuedAd(BaseModel):
    """O intrare in coada de aprobare umana ``proposed_ads_queue.json``."""

    created_at: datetime
    target_keyword: str
    emotion_trigger: str
    framework_name: str
    framework_style: FrameworkStyle
    product_usp: str
    ad: AdCopy
    status: Literal["pending_review"] = "pending_review"


class AdQueue(BaseModel):
    """Fisierul ``proposed_ads_queue.json`` in intregime."""

    queue: list[QueuedAd] = Field(default_factory=list)
