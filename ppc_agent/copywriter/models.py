"""Structuri de date tipizate pentru modulul de copywriting."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FrameworkStyle = Literal["pas", "status", "fomo", "aida"]
OmniPlatform = Literal["google", "meta", "tiktok"]

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


class OmniSwipeRecord(BaseModel):
    """O intrare in biblioteca omnicanal (Google/Meta/TikTok) cu performanta dovedita.

    Spre deosebire de :class:`TikTokSwipeRecord` (un singur canal), aceasta
    schema unifica toate platformele si separa explicit trei zone: identitatea
    anuntului (asset), semnalele de validare de tip proxy — ``longevity_days``
    si ``variation_count`` (un anunt care ruleaza mult timp sau are multe
    variante active e, de regula, profitabil — spre deosebire de un ROI
    auto-raportat, usor de umflat) — si copy-ul semantic propriu-zis.
    """

    # Asset
    ad_id: str
    platform: OmniPlatform
    niche: str
    format: str

    # Validation proxy
    longevity_days: int | None = None
    variation_count: int | None = None
    performance_signal: str

    # Semantic / copy
    hook_type: str
    hook_text: str
    problem_agitation: str
    mechanism_proof: str
    offer_cta: str


class OmniAdCopy(BaseModel):
    """Copy-ul final generat pentru un anunt omnicanal (Google/Meta/TikTok)."""

    hook_type: str
    hook_text: str
    problem_agitation: str
    mechanism_proof: str
    offer_cta: str

    def as_dict(self) -> dict[str, str]:
        """Forma ceruta la iesire — aceleasi 5 chei semantice ca :class:`OmniSwipeRecord`."""
        return {
            "hook_type": self.hook_type,
            "hook_text": self.hook_text,
            "problem_agitation": self.problem_agitation,
            "mechanism_proof": self.mechanism_proof,
            "offer_cta": self.offer_cta,
        }


class OmniCopySpec(BaseModel):
    """Tot ce ii trebuie unui :class:`~ppc_agent.copywriter.llm.BaseLLMClient` sa
    genereze un :class:`OmniAdCopy`."""

    product_usp: str
    niche: str
    target_platform: OmniPlatform
    examples: list[OmniSwipeRecord] = Field(default_factory=list)
    system_prompt: str


class SwipeFile(BaseModel):
    """Continutul ``swipe_file.json``."""

    frameworks: list[Framework] = Field(min_length=1)
    tiktok_swipe_library: list[TikTokSwipeRecord] = Field(default_factory=list)
    omnichannel_swipe_library: list[OmniSwipeRecord] = Field(default_factory=list)

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


class StoryboardSpec(BaseModel):
    """Tot ce ii trebuie unui :class:`~ppc_agent.copywriter.llm.BaseLLMClient` sa
    genereze un :class:`~ppc_agent.creative.video_models.Storyboard`."""

    product_usp: str
    target_keyword: str
    examples: list[TikTokSwipeRecord] = Field(default_factory=list)
    system_prompt: str


class ReportSummarySpec(BaseModel):
    """Tot ce ii trebuie unui model ca sa scrie rezumatul executiv al unui raport.

    ``facts`` sunt deja formulate, cu cifrele exacte: modelul le reformuleaza,
    nu le calculeaza. ``template`` e rezumatul determinist construit din
    aceleasi fapte - il intoarce clientul ``mock`` si ramane rezerva cand
    textul modelului nu trece verificarea cifrelor.
    """

    system_prompt: str
    facts: list[str]
    template: str


class ReportSummary(BaseModel):
    """Rezumatul executiv scris de model."""

    summary: str = Field(min_length=1)


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
