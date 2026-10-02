"""CCO-ul (Chief Creative Officer): judeca o creativa (imagine sau video scurt) ca un
Senior Media Buyer de performanta - inainte de bani, nu dupa.

Impartirea muncii, ca in restul consiliului: modelul Ollama cu vision
(``OLLAMA_VISION_MODEL``) doar OBSERVA fapte (domeniul, daca se vede firma, conditiile,
greselile de scriere, cate blocuri de text concureaza, care e hook-ul si daca domina,
la video: intro de brand, hook de text). Scorurile si decizia le calculeaza CODUL, dupa
reguli fixe - "HUMAN REVIEW REQUIRED" nu depinde de dispozitia unui model de 4B:

- **Trust** (prioritatea 0): in domeniile sensibile (recrutare, financiar, sanatate),
  fara firma identificabila, scorul cade sub 4 si decizia e ``HUMAN_REVIEW_REQUIRED``;
  conditiile lipsa si greselile masive de scriere scad si ele; o imagine stock nu e rea
  in sine, dar e penalizata cand textul pretinde ca e echipa sau clientul real;
- **Ierarhie si incarcare cognitiva**: peste 3 blocuri de text concurente sau hook-ul
  ingropat in text mic = incarcare MARE (scor slab);
- **Hook power**: la imagine, impactul la prima privire, plafonat cand hook-ul nu domina;
  la video, primele 3 secunde - timpul mort (cadru inghetat sau negru peste o secunda,
  masurat de ffmpeg, nu ghicit) sau un intro de logo il prabusesc;
- **Format**: masurat din dimensiunile fisierului (4:5 si 9:16 sunt nativele Meta/TikTok).

Imaginea sta in memorie; video-ul se scrie temporar pe disc doar cat il citeste ffmpeg.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent_server.services.llm_client import (
    LLMError,
    LLMUnavailableError,
    OllamaChatClient,
    ollama_model_tag,
)
from ppc_agent_server.settings import ServerSettings

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
#: Cat poate scrie modelul de vision. Pe CPU, gemma3:4b a codat o imagine in ~3 minute si
#: n-a terminat JSON-ul in plafonul chatului (300 s): o evaluare e rara si limitata pe ora.
VISION_MAX_GENERATION_SECONDS = 900.0
#: Cadrele din primele 3 secunde ale unui video, trimise modelului.
VIDEO_FRAME_SECONDS = (0.0, 1.0, 2.0, 3.0)
#: Sub atat, decizia e ``HUMAN_REVIEW_REQUIRED``.
TRUST_FLOOR = 4
#: Sub atat (hook, ierarhie, format), creativa se repara inainte de test.
TEST_FLOOR = 5
#: Peste atatea blocuri de text concurente, ochiul nu mai stie unde sa se uite.
MAX_TEXT_BLOCKS = 3
#: Greseli de scriere de la care sunt "masive".
MASSIVE_TYPOS = 3

AssetType = Literal["image", "video"]
Decision = Literal["ELIGIBLE_FOR_TEST", "REVISE_BEFORE_TEST", "HUMAN_REVIEW_REQUIRED"]
Domain = Literal["recruitment", "finance", "health", "other"]
_SENSITIVE: frozenset[str] = frozenset({"recruitment", "finance", "health"})
_DOMAIN_NAMES = {"recruitment": "recrutare", "finance": "financiar", "health": "sănătate"}


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


_Word = Annotated[str, Field(max_length=40)]
_Sentence = Annotated[str, Field(max_length=180)]


class _Observation(BaseModel):
    """Ce vede modelul - fapte, nu verdicte. Impus prin schema, validat inainte de calcul."""

    domain: Domain
    brand_identity_visible: bool
    conditions_stated: bool
    # Fiecare text si fiecare lista au plafon: Ollama le impune prin gramatica, deci un
    # model mic intrat in bucla (vazut real: "token repeat limit reached") nu are unde creste.
    spelling_errors: list[_Word] = Field(max_length=8)
    stock_photo: bool
    claims_authentic: bool
    text_blocks: int = Field(ge=0, le=30)
    main_hook: str = Field(max_length=120)
    hook_is_dominant: bool
    visual_hook: int = Field(ge=0, le=10)
    text_hook_present: bool
    opens_with_brand_intro: bool
    risks: list[_Sentence] = Field(max_length=3)
    fixes: list[_Sentence] = Field(min_length=1, max_length=3)


class CreativeScores(BaseModel):
    trust: int = Field(ge=0, le=10)
    hook_power: int = Field(ge=0, le=10)
    cognitive_load_and_hierarchy: int = Field(ge=0, le=10)
    format_suitability: int = Field(ge=0, le=10)


class CreativeEvaluation(BaseModel):
    """Raspunsul CCO-ului."""

    asset_type: AssetType
    decision: Decision
    scores: CreativeScores
    detected_risks: list[str]
    priority_fixes: list[str] = Field(max_length=3)


_SYSTEM = (
    "You are a senior performance media buyer checking ONE ad before money is spent on "
    "it ({what}). Report FACTS you can see; do not score the ad. Read every text on it.\n"
    "- domain: recruitment (ANY job offer, even a job in healthcare or care), finance "
    "(loans, investments), health (medical services or products), or other.\n"
    "- brand_identity_visible: a logo or a company name is visible (a phone number alone "
    "is NOT an identity).\n"
    "- conditions_stated: the key terms are on the ad (for a job: pay, place, duration, "
    "employer; for finance: costs, rates; for health: who provides it).\n"
    "- spelling_errors: each misspelled word or missing diacritic exactly as written "
    "(Romanian text: «CĂUTA» instead of «CAUTĂ» counts). Empty list if none.\n"
    "- stock_photo: the people look like a stock photo. claims_authentic: the text claims "
    "they are the real team, staff or clients.\n"
    "- text_blocks: how many separate text blocks compete for attention.\n"
    "- main_hook: the strongest BENEFIT for the viewer (money, result, saving), as written "
    "- not the title or the job description. hook_is_dominant: that benefit is the "
    "biggest, first-read element (false if it sits in smaller text under a title).\n"
    "- visual_hook: 0-10, impact at first glance in a fast feed.\n"
    "- text_hook_present: a short, readable text hook is visible{video_hook}.\n"
    "- opens_with_brand_intro: {intro}.\n"
    "- risks: up to 3 other risks to conversion with the ad's real audience (the people "
    "who read the ad's language) - no reach or targeting advice. fixes: up to 3 concrete "
    "fixes for THIS ad, each naming the element and the change, most important first.\n"
    "LANGUAGE: main_hook exact ca pe reclamă; risks și fixes scrise în limba română."
)
_IMAGE_PROMPT = _SYSTEM.format(
    what="an image", video_hook="", intro="always false for an image"
)
_VIDEO_PROMPT = _SYSTEM.format(
    what=(
        "a short video; you get its frames at 0, 1, 2 and 3 seconds, in order - judge the "
        "first 3 seconds"
    ),
    video_hook=" in the first 3 seconds",
    intro="the video opens with a logo or brand card instead of the product, a person or motion",
)


# --- fisierul: tip, dimensiuni ----------------------------------------------------


def asset_kind(data: bytes) -> AssetType | None:
    """Imagine (JPEG/PNG) sau video (MP4/MOV/WebM), dupa semnatura - nu dupa extensie."""
    if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        return "image"
    if data[4:8] == b"ftyp" or data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video"
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """Latimea si inaltimea unei imagini PNG/JPEG, citite din antet (fara Pillow)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        # SOF0-SOF15, fara DHT (C4), JPG (C8) si DAC (CC): acolo stau dimensiunile.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        index += 2 + length
    return None


#: Raportul latime/inaltime -> scorul de format, pe tip. 4:5 e nativul feed-ului Meta,
#: 9:16 al Reels/Stories/TikTok; 3:4 trece, dar feed-ul il taie la 4:5.
_FORMAT_SCORES: dict[AssetType, tuple[tuple[float, int, str], ...]] = {
    "image": (
        (0.8, 10, "4:5"), (0.5625, 9, "9:16"), (1.0, 8, "1:1"), (0.75, 7, "3:4"),
        (1.91, 5, "1.91:1"), (16 / 9, 5, "16:9"),
    ),
    "video": ((0.5625, 10, "9:16"), (0.8, 8, "4:5"), (1.0, 7, "1:1"), (16 / 9, 4, "16:9")),
}


def format_suitability(
    asset: AssetType, width: int, height: int
) -> tuple[int, list[str], list[str]]:
    """Scorul de format, riscurile si remedierile lui (liste goale cand e nativ)."""
    ratio = width / height
    score, name = next(
        ((score, name) for target, score, name in _FORMAT_SCORES[asset]
         if abs(ratio - target) <= 0.02),
        (3, f"{width}x{height}"),
    )
    risks: list[str] = []
    fixes: list[str] = []
    native = "4:5 (1080x1350)" if asset == "image" else "9:16 (1080x1920)"
    if score < 10:
        risks.append(f"format {name}: nu e nativ pentru feed; recomandat {native}")
        fixes.append(f"Exportă în {native}")
    if min(width, height) < 600:
        score = max(0, score - 3)
        risks.append(f"rezoluție mică ({width}x{height}): sub 600 px pe latura mică")
        fixes.append(f"Exportă la rezoluție completă, {native}")
    return score, risks, fixes


# --- video: cadrele si timpul mort, cu ffmpeg ----------------------------------------


def _ffmpeg() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SetupRequiredError("Evaluarea video cere ffmpeg și ffprobe în PATH.")
    return ffmpeg, ffprobe


def _video_facts(data: bytes) -> tuple[list[bytes], int, int, bool]:
    """Cadrele din primele 3 secunde (PNG), dimensiunile si daca exista timp mort.

    Timpul mort se masoara, nu se ghiceste: ``freezedetect`` (cadru neschimbat) si
    ``blackdetect`` (negru) peste o secunda, in primele 3 secunde.
    """
    ffmpeg, ffprobe = _ffmpeg()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "creativa"
        path.write_bytes(data)
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height:format=duration", "-of", "json", str(path)],
                capture_output=True, timeout=30, check=True,
            )
            info = json.loads(probe.stdout)
            stream = info["streams"][0]
            width, height = int(stream["width"]), int(stream["height"])
            duration = float(info.get("format", {}).get("duration", 0) or 0)
            frames = [
                subprocess.run(
                    [ffmpeg, "-v", "error", "-ss", str(second), "-i", str(path),
                     "-frames:v", "1", "-vf", "scale=720:-2", "-f", "image2pipe",
                     "-c:v", "png", "-"],
                    capture_output=True, timeout=60, check=True,
                ).stdout
                for second in VIDEO_FRAME_SECONDS
                if second < max(duration, 0.1)
            ]
            scan = subprocess.run(
                [ffmpeg, "-v", "info", "-t", "3", "-i", str(path), "-an", "-vf",
                 "freezedetect=n=-60dB:d=1,blackdetect=d=1:pix_th=0.10", "-f", "null", "-"],
                capture_output=True, timeout=60, check=True,
            )
        except (subprocess.SubprocessError, OSError, KeyError, IndexError, ValueError) as exc:
            raise ValueError("video-ul nu se poate citi (MP4/MOV/WebM valid?)") from exc
    dead_air = bool(re.search(rb"freeze_start|black_start", scan.stderr))
    return [frame for frame in frames if frame], width, height, dead_air


# --- decizia (cod, nu model) ---------------------------------------------------------


def _clamp(value: int) -> int:
    return max(0, min(10, value))


def _trust(seen: _Observation, risks: list[str], fixes: list[str]) -> int:
    score = 10
    sensitive = seen.domain in _SENSITIVE
    if not seen.brand_identity_visible:
        risks.append("lipsește identitatea: niciun logo sau nume de firmă verificabil")
        fixes.append("Adaugă numele firmei și logo-ul (plus licența, unde e cerută)")
        score = min(score, 3) if sensitive else score - 3
    if sensitive and not seen.conditions_stated:
        risks.append("condițiile ofertei nu sunt pe reclamă")
        fixes.append("Pune condițiile esențiale ale ofertei în textul reclamei")
        score -= 3
    typos = len(seen.spelling_errors)
    if typos:
        shown = ", ".join(f"«{word}»" for word in seen.spelling_errors[:4])
        risks.append(f"greșeli de scriere ({typos}): {shown}")
        if typos >= MASSIVE_TYPOS:
            fixes.append("Corectează ortografia și diacriticele")
            score -= 4
        else:
            score -= 1
    if seen.stock_photo and seen.claims_authentic:
        risks.append("fotografie stock prezentată drept echipa sau clienții reali")
        fixes.append("Înlocuiește fotografia stock cu una reală sau scoate pretenția")
        score -= 4
    if sensitive:
        risks.insert(0, f"domeniu sensibil ({_DOMAIN_NAMES[seen.domain]}): încrederea decide")
    return _clamp(score)


def _hierarchy(seen: _Observation, risks: list[str], fixes: list[str]) -> int:
    blocks = seen.text_blocks
    score = 9 if blocks <= 2 else 7 if blocks == MAX_TEXT_BLOCKS else 4 - (blocks - 4)
    if blocks > MAX_TEXT_BLOCKS:
        risks.append(f"{blocks} blocuri de text concurente: ochiul nu știe unde să se uite")
        fixes.append("Păstrează pe imagine maximum 3 blocuri; restul merge în textul reclamei")
    if not seen.hook_is_dominant:
        score = min(score, 4)
        hook = f"«{seen.main_hook}»" if seen.main_hook else "hook-ul principal"
        risks.append(f"hook-ul principal ({hook}) e îngropat în text mic")
        fixes.append(f"Fă din {hook} elementul cel mai mare, citit primul")
    return _clamp(max(score, 1))


def _hook(
    seen: _Observation, asset: AssetType, dead_air: bool, risks: list[str], fixes: list[str]
) -> int:
    score = seen.visual_hook
    if not seen.hook_is_dominant:
        score = min(score, 5)
    if asset == "video":
        if dead_air:
            score = min(score, 3)
            risks.append("timp mort în primele 3 secunde (cadru înghețat sau negru peste 1 s)")
            fixes.append("Începe direct cu mișcare sau cu produsul, din prima secundă")
        if seen.opens_with_brand_intro:
            score = min(score, 3)
            risks.append("video-ul începe cu un intro de brand/logo")
            fixes.append("Mută logo-ul la final; primele 3 secunde sunt pentru hook")
        if not seen.text_hook_present:
            score -= 2
            risks.append("niciun hook de text în primele 3 secunde")
    return _clamp(score)


def _decide(scores: CreativeScores) -> Decision:
    if scores.trust < TRUST_FLOOR:
        return "HUMAN_REVIEW_REQUIRED"
    weakest = min(scores.hook_power, scores.cognitive_load_and_hierarchy, scores.format_suitability)
    return "REVISE_BEFORE_TEST" if weakest < TEST_FLOOR else "ELIGIBLE_FOR_TEST"


def _unique(items: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        text = item.strip().rstrip(".")
        if text and text.lower() not in seen:
            seen[text.lower()] = text
    return list(seen.values())


def evaluate_creative(media: bytes | str | Path, *, model: VisionModel) -> dict[str, Any]:
    """Evaluarea CCO-ului: tipul, decizia, cele 4 scoruri, riscurile si top 3 remedieri.

    Args:
        media: Imaginea (JPEG/PNG) sau video-ul (MP4/MOV/WebM) - octetii sau calea.
        model: Modelul cu vision (vezi :func:`vision_model_from_settings`).

    Raises:
        ValueError: nu e imagine/video suportat, e prea mare sau nu se poate citi.
        SetupRequiredError: Ollama nu raspunde sau lipseste ffmpeg (-> 503).
        ProviderError: modelul a picat sau a raspuns altceva decat faptele cerute (-> 502).
    """
    data = media if isinstance(media, bytes) else Path(media).read_bytes()
    asset = asset_kind(data)
    if asset is None:
        raise ValueError("doar imagini JPEG/PNG sau video MP4/MOV/WebM")
    limit = MAX_IMAGE_BYTES if asset == "image" else MAX_VIDEO_BYTES
    if len(data) > limit:
        raise ValueError(f"fișierul depășește {limit // (1024 * 1024)} MB")
    dead_air = False
    if asset == "image":
        size = image_size(data)
        if size is None:
            raise ValueError("imaginea nu se poate citi")
        frames = [data]
    else:
        frames, width, height, dead_air = _video_facts(data)
        if not frames:
            raise ValueError("video-ul nu are cadre în primele 3 secunde")
        size = (width, height)
    try:
        raw = model.complete(
            system=_IMAGE_PROMPT if asset == "image" else _VIDEO_PROMPT,
            user="Analizează reclama atașată.",
            images=[base64.b64encode(frame).decode("ascii") for frame in frames],
            schema=_Observation.model_json_schema(),
        )
    except LLMUnavailableError as exc:
        raise SetupRequiredError(str(exc)) from exc
    except LLMError as exc:
        raise ProviderError(f"evaluarea creativei a picat: {exc}") from exc
    try:
        seen = _Observation.model_validate_json(raw)
    except ValidationError as exc:
        raise ProviderError("modelul de vision a întors un răspuns invalid") from exc

    risks: list[str] = []
    fixes: list[str] = []
    trust = _trust(seen, risks, fixes)
    hierarchy = _hierarchy(seen, risks, fixes)
    hook = _hook(seen, asset, dead_air, risks, fixes)
    format_score, format_risks, format_fixes = format_suitability(asset, *size)
    risks += format_risks
    fixes += format_fixes
    scores = CreativeScores(
        trust=trust,
        hook_power=hook,
        cognitive_load_and_hierarchy=hierarchy,
        format_suitability=format_score,
    )
    # Regulile intai (sigure, in ordinea prioritatii: incredere, ierarhie, hook, format),
    # apoi ce a mai vazut modelul.
    return CreativeEvaluation(
        asset_type=asset,
        decision=_decide(scores),
        scores=scores,
        detected_risks=_unique([*risks, *seen.risks]),
        priority_fixes=_unique([*fixes, *seen.fixes])[:3],
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
        # Samanta fixa: aceeasi creativa primeste aceleasi fapte, deci aceleasi scoruri. Nu
        # temperatura 0: decodarea greedy a bagat modelul mic in bucla de repetitie.
        temperature=0.2,
        seed=7,
        max_tokens=900,
        max_generation=VISION_MAX_GENERATION_SECONDS,
    )
