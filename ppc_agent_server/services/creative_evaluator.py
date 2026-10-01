"""CCO-ul (Chief Creative Officer): judeca o creativa ca un Senior Art Director si ca
algoritmii de Discovery ai Meta (Explore, Reels) si TikTok (For You).

Doua familii de criterii, fiecare notata de un model Ollama cu vision
(``OLLAMA_VISION_MODEL``), intr-un JSON impus prin schema (``format`` Ollama):

- **Estetica** (scala lui Aesthetic Predictor V2.5, 1-10: peste 5,5 profesionist,
  peste 8 premium): compozitia, balanta culorilor, zgomotul vizual, calitatea perceputa.
  Modelul IMITA scala predictorului (un cap de regresie peste embedding-uri SigLIP);
  nu ruleaza predictorul - acela cere PyTorch si greutatile lui;
- **Euristicile algoritmilor**: hook-ul vizual (impactul la prima privire - la o
  imagine, sub o secunda in feed; la video, primele 3 secunde), puterea de a opri
  scroll-ul (contrast, fete expresive, unghiuri neobisnuite), incarcarea cognitiva
  (cat de repede intelege creierul mesajul), plus textul pe imagine si CTA-ul.

Modelul doar noteaza si propune remedieri. Scorul estetic, potentialul viral
(High/Medium/Low) si verdictul pentru algoritmi le calculeaza codul, din note - ca
restul consiliului, verdictul nu il da un LLM. "Potential viral" e o euristica din
semnalele pe care algoritmii le rasplatesc, nu o predictie: din o singura imagine nu se
poate prezice viralitatea. Imaginea nu se scrie pe disc: sta in memorie.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent_server.services.llm_client import (
    LLMError,
    LLMUnavailableError,
    OllamaChatClient,
    ollama_model_tag,
)
from ppc_agent_server.settings import ServerSettings

#: Imaginile mai mari nu aduc nimic in plus modelului, doar timp pe CPU.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
#: Formatele pe care le citeste Ollama, dupa semnatura fisierului (nu dupa extensie).
_SIGNATURES = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png"}

#: Cat poate scrie modelul de vision. Pe CPU, gemma3:4b a codat o imagine in ~3 minute si
#: n-a terminat JSON-ul in plafonul chatului (300 s): o evaluare e rara si limitata pe ora,
#: deci poate astepta mai mult decat un mesaj de chat.
VISION_MAX_GENERATION_SECONDS = 900.0

#: Pragurile scalei estetice (Aesthetic Predictor V2.5).
PROFESSIONAL = Decimal("5.5")
PREMIUM = Decimal("8")
#: Potentialul viral, din media hook / thumb-stop / incarcare cognitiva (0-10).
HIGH_VIRALITY = Decimal("7")
LOW_VIRALITY = Decimal("4.5")

ViralityPotential = Literal["High", "Medium", "Low"]


class VisionModel(Protocol):
    """Un model care vede imagini (``OllamaChatClient`` cu un model de vision)."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        images: Sequence[str] = (),
        schema: Mapping[str, Any] | None = None,
    ) -> str: ...


def _mark(low: int = 0) -> Any:
    return Field(ge=low, le=10)


class _Ratings(BaseModel):
    """Ce intoarce modelul - impus prin schema, validat inainte de orice calcul."""

    composition: int = _mark(1)
    color_balance: int = _mark(1)
    visual_noise: int = _mark(1)
    perceived_quality: int = _mark(1)
    visual_hook: int = _mark()
    thumb_stop: int = _mark()
    cognitive_load: int = _mark()
    text_density: int = _mark()
    cta_clarity: int = _mark()
    #: Ce se vede, intr-o fraza: subiectul, fete, contrastul.
    observation: str = Field(min_length=1, max_length=300)
    #: Remedierile concrete, de Media Buyer de performanta, cea mai importanta prima.
    fixes: list[str] = Field(min_length=1, max_length=3)


class CreativeEvaluation(BaseModel):
    """Raspunsul CCO-ului."""

    aesthetic_score: float = Field(ge=1, le=10)
    virality_potential: ViralityPotential
    algorithm_compatibility: str
    feedback: str


_SYSTEM = (
    "You are a senior art director and a performance media buyer reviewing ONE ad image "
    "for Meta (Feed, Explore, Reels) and TikTok. Judge only what is visible. Integers.\n"
    "AESTHETICS, 1-10, on the Aesthetic Predictor V2.5 scale (above 5.5 = professional, "
    "above 8 = premium; most stock-like ads are 5-6):\n"
    "- composition: clear focal point, balance, rule of thirds, breathing room.\n"
    "- color_balance: harmonious palette, controlled saturation, intentional contrast.\n"
    "- visual_noise: 10 = clean, one message; 1 = cluttered, competing elements.\n"
    "- perceived_quality: sharpness, lighting, no compression artifacts, no stock feel.\n"
    "ALGORITHM SIGNALS, 0-10:\n"
    "- visual_hook: impact at first glance in a fast-scrolling feed (under one second).\n"
    "- thumb_stop: high contrast, expressive human faces, unusual angles, pattern break.\n"
    "- cognitive_load: 10 = the message is understood instantly, 0 = it needs effort.\n"
    "- text_density: 10 = little or no text on the image, 0 = mostly text.\n"
    "- cta_clarity: 10 = the call to action is obvious, 0 = there is none.\n"
    "Then observation = one sentence on what the ad is (read the main text on the image: "
    "what it offers or asks) and what the visual shows; fixes = up to 3 concrete, technical "
    "fixes a performance media buyer would ask for THIS image, each naming the exact element "
    "and the change, most important first. Do not invent brands, prices or numbers that are "
    "not on the image.\n"
    "LANGUAGE: observation and fixes MUST be written in Romanian (limba română), even "
    "though these instructions are in English."
)
_USER = "Evaluează creativa atașată."

#: Ce cere un media buyer cand semnalul e cel mai slab - actiunea standard, fixa.
_PRIORITY = {
    "visual_hook": "un element dominant care se citește într-o fracțiune de secundă",
    "thumb_stop": "contrast mai mare, o față expresivă sau un unghi neobișnuit",
    "cognitive_load": "un singur mesaj pe imagine; restul merge în textul reclamei",
    "text_density": "tai textul de pe imagine la titlu și ofertă",
    "cta_clarity": "îndemnul mare, pe o bandă sau un buton contrastant",
}
_SIGNAL_NAMES = {
    "visual_hook": "hook-ul vizual",
    "thumb_stop": "oprirea scroll-ului",
    "cognitive_load": "încărcarea cognitivă",
    "text_density": "textul pe imagine",
    "cta_clarity": "CTA-ul",
}


def image_kind(data: bytes) -> str | None:
    """``jpeg``/``png`` dupa semnatura fisierului, sau ``None`` daca nu e una dintre ele."""
    return next((kind for magic, kind in _SIGNATURES.items() if data.startswith(magic)), None)


def _image_bytes(image: bytes | str | Path) -> bytes:
    data = image if isinstance(image, bytes) else Path(image).read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"imaginea depășește {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    if image_kind(data) is None:
        raise ValueError("doar imagini JPEG sau PNG")
    return data


def _mean(*marks: int) -> Decimal:
    return (Decimal(sum(marks)) / len(marks)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _ro(value: Decimal) -> str:
    return str(value).replace(".", ",")


def _tier(score: Decimal) -> str:
    if score > PREMIUM:
        return "premium"
    if score > PROFESSIONAL:
        return "profesionist"
    return "sub pragul profesionist de 5,5"


def _virality(index: Decimal, aesthetic: Decimal) -> ViralityPotential:
    """High doar cu semnale puternice SI o imagine profesionista: un hook bun pe o
    imagine amatoare opreste scroll-ul, dar nu tine increderea."""
    if index >= HIGH_VIRALITY and aesthetic > PROFESSIONAL:
        return "High"
    if index < LOW_VIRALITY:
        return "Low"
    return "Medium"


def _compatibility(ratings: _Ratings, index: Decimal, potential: ViralityPotential) -> str:
    """Cum o trateaza algoritmii de Discovery - din semnalele pe care le rasplatesc."""
    signals = (
        f"hook {ratings.visual_hook}/10, oprirea scroll-ului {ratings.thumb_stop}/10, "
        f"încărcare cognitivă {ratings.cognitive_load}/10; indice {_ro(index)}"
    )
    verdict = {
        "High": (
            "are semnalele pe care Explore și Reels le împing: oprește scroll-ul și se "
            "înțelege instant, deci câștigă atenție ieftin"
        ),
        "Medium": (
            "trece prin feed, dar nu oprește destul scroll-ul ca să fie împinsă în "
            "Explore sau Reels: distribuția rămâne în mare parte plătită"
        ),
        "Low": (
            "va fi derulată: algoritmii o vor arăta puțin și scump, pentru că oamenii nu "
            "se opresc pe ea"
        ),
    }[potential]
    if potential == "Medium" and index >= HIGH_VIRALITY:
        # Semnalele erau de High; a oprit-o pragul estetic - spunem motivul real.
        verdict = (
            "oprește scroll-ul, dar arată amator (estetic sub 5,5): oamenii se opresc, nu "
            "capătă încredere, iar Explore și Reels nu o împing mai departe"
        )
    text = f"Pe Meta, {verdict} ({signals})."
    if ratings.text_density < 5:
        text += " Mult text pe imagine: Meta nu o mai respinge, dar o difuzează mai greu."
    return (
        f"{text} Pe TikTok, distribuția o primește video-ul: imaginea merge ca prim cadru "
        "sau într-un carusel foto, unde contează aceleași prime fracțiuni de secundă."
    )


def evaluate_creative(image: bytes | str | Path, *, model: VisionModel) -> dict[str, Any]:
    """Evaluarea CCO-ului: scorul estetic, potentialul viral, algoritmii si feedback-ul.

    Args:
        image: Imaginea (octetii ei) sau calea catre ea.
        model: Modelul cu vision (vezi :func:`vision_model_from_settings`).

    Raises:
        ValueError: nu e o imagine JPEG/PNG sau e prea mare.
        SetupRequiredError: Ollama nu raspunde (-> 503).
        ProviderError: modelul a picat sau a intors altceva decat notele cerute (-> 502).
    """
    encoded = base64.b64encode(_image_bytes(image)).decode("ascii")
    try:
        raw = model.complete(
            system=_SYSTEM,
            user=_USER,
            images=[encoded],
            schema=_Ratings.model_json_schema(),
        )
    except LLMUnavailableError as exc:
        raise SetupRequiredError(str(exc)) from exc
    except LLMError as exc:
        raise ProviderError(f"evaluarea creativei a picat: {exc}") from exc
    try:
        ratings = _Ratings.model_validate_json(raw)
    except ValidationError as exc:
        raise ProviderError("modelul de vision a întors un răspuns invalid") from exc

    aesthetic = _mean(
        ratings.composition, ratings.color_balance, ratings.visual_noise, ratings.perceived_quality
    )
    index = _mean(ratings.visual_hook, ratings.thumb_stop, ratings.cognitive_load)
    potential = _virality(index, aesthetic)
    signals = {name: getattr(ratings, name) for name in _PRIORITY}
    weakest = min(signals, key=lambda name: signals[name])
    fixes = "; ".join(
        f"{number}) {fix.strip().rstrip('.')}" for number, fix in enumerate(ratings.fixes, 1)
    )
    feedback = (
        f"Estetic: {_ro(aesthetic)}/10, {_tier(aesthetic)} (compoziție {ratings.composition}, "
        f"culori {ratings.color_balance}, zgomot vizual {ratings.visual_noise}, calitate "
        f"{ratings.perceived_quality}). {ratings.observation.strip()} Ce schimbi: {fixes}. "
        f"Cel mai slab semnal e {_SIGNAL_NAMES[weakest]} ({signals[weakest]}/10): "
        f"{_PRIORITY[weakest]}."
    )
    return CreativeEvaluation(
        aesthetic_score=float(aesthetic),
        virality_potential=potential,
        algorithm_compatibility=_compatibility(ratings, index, potential),
        feedback=feedback,
    ).model_dump()


def vision_model_from_settings(settings: ServerSettings) -> OllamaChatClient:
    """Clientul Ollama pe modelul de vision din ``.env``.

    Raises:
        SetupRequiredError: lipseste ``OLLAMA_HOST`` sau ``OLLAMA_VISION_MODEL`` (-> 503).
    """
    if not settings.ollama_host or not settings.ollama_vision_model:
        raise SetupRequiredError(
            "Evaluarea creativelor nu e configurată: setează OLLAMA_HOST și "
            "OLLAMA_VISION_MODEL (un model cu vision, ex. qwen2.5vl:3b)."
        )
    return OllamaChatClient(
        host=settings.ollama_host,
        model=ollama_model_tag(settings.ollama_vision_model),
        first_token_timeout=settings.ollama_first_token_timeout,
        keep_alive=settings.ollama_keep_alive or None,
        # 0 = decodare greedy: aceeasi imagine primeste aceleasi note. Cu 0,2, aceeasi
        # creativa a iesit 5,3 (Medium) intr-o rulare si 6,5 (High) in alta.
        temperature=0.0,
        # JSON-ul cu 9 note, observatia si 3 remedieri depaseste plafonul de text al chatului.
        max_tokens=700,
        max_generation=VISION_MAX_GENERATION_SECONDS,
    )
