"""Incarcarea ``swipe_file.json`` si recuperarea framework-ului potrivit (RAG local).

Recuperarea nu foloseste embeddings: potriveste declansatorul emotional cerut
cu campurile ``style`` / ``trigger`` / ``name`` ale framework-urilor prin
suprapunere de jetoane si sinonime. Suficient pentru un catalog mic si curat, si
fara dependinte noi.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ppc_agent.copywriter.models import Framework, SwipeFile, TikTokSwipeRecord
from ppc_agent.errors import SwipeFileError
from ppc_agent.texttools import normalize, tokenize

_DEFAULT_TIKTOK_EXAMPLES = 2

# Sinonime pentru declansatorul emotional -> stil de framework.
_TRIGGER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "pas": (
        "frica", "teama", "urgenta", "risc", "pericol", "problema", "defect",
        "pierdere", "avarie", "fear", "urgency", "pain",
    ),
    "status": (
        "statut", "status", "exclusivitate", "prestigiu", "dorinta", "lux",
        "eleganta", "validare", "imagine", "desire", "premium",
    ),
    "fomo": (
        "fomo", "lipsa", "scarcitate", "stoc limitat", "deadline", "termen",
        "acum sau niciodata", "oferta limitata", "scarcity", "loss aversion",
    ),
    "aida": (
        "curiozitate", "beneficiu", "interes", "atentie", "economie de timp",
        "rezultat", "curiosity", "benefit", "attention",
    ),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_swipe_path() -> Path:
    """Calea implicita catre ``swipe_file.json`` (radacina proiectului)."""
    return _repo_root() / "swipe_file.json"


def load_swipe_file(path: Path | str | None = None) -> SwipeFile:
    """Incarca si valideaza ``swipe_file.json``.

    Args:
        path: Cale explicita. Daca lipseste, se foloseste :func:`default_swipe_path`.

    Returns:
        Continutul validat.

    Raises:
        SwipeFileError: Daca fisierul lipseste, nu e JSON valid, sau nu trece
            validarea de schema.
    """
    resolved = Path(path) if path is not None else default_swipe_path()
    if not resolved.is_file():
        raise SwipeFileError(f"swipe_file.json nu a fost gasit la {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwipeFileError(f"swipe_file.json nu e JSON valid: {exc}") from exc
    try:
        return SwipeFile.model_validate(raw)
    except ValidationError as exc:
        raise SwipeFileError(f"swipe_file.json nu respecta schema: {exc}") from exc


def _score(framework: Framework, trigger_tokens: set[str], trigger_norm: str) -> int:
    score = 0
    for synonym in _TRIGGER_SYNONYMS.get(framework.style, ()):
        if synonym in trigger_norm or set(tokenize(synonym)) & trigger_tokens:
            score += 2
    haystack = set(tokenize(f"{framework.name} {framework.trigger}"))
    score += len(haystack & trigger_tokens)
    if framework.style in trigger_norm:
        score += 3
    return score


def retrieve_framework(swipe: SwipeFile, emotion_trigger: str) -> Framework:
    """Alege framework-ul care se potriveste cel mai bine cu ``emotion_trigger``.

    Args:
        swipe: Continutul swipe file.
        emotion_trigger: Declansatorul emotional cerut (ex. ``"frica"``, ``"status"``,
            ``"fomo"``, sau o descriere mai lunga).

    Returns:
        Framework-ul cu scorul de potrivire cel mai mare.

    Raises:
        SwipeFileError: Daca niciun framework nu se potriveste (scor 0).
    """
    trigger_norm = normalize(emotion_trigger)
    trigger_tokens = set(tokenize(emotion_trigger))
    ranked = sorted(
        swipe.frameworks,
        key=lambda framework: _score(framework, trigger_tokens, trigger_norm),
        reverse=True,
    )
    best = ranked[0]
    if _score(best, trigger_tokens, trigger_norm) == 0:
        available = ", ".join(f"{f.style} ({f.name})" for f in swipe.frameworks)
        raise SwipeFileError(
            f"niciun framework pentru declansatorul '{emotion_trigger}'. "
            f"Disponibile: {available}"
        )
    return best


def _niche_overlap(record: TikTokSwipeRecord, keyword_tokens: set[str]) -> int:
    haystack = set(tokenize(f"{record.niche} {record.format}"))
    return len(haystack & keyword_tokens)


def retrieve_tiktok_examples(
    swipe: SwipeFile, target_keyword: str, *, limit: int = _DEFAULT_TIKTOK_EXAMPLES
) -> list[TikTokSwipeRecord]:
    """Cele mai relevante intrari din ``tiktok_swipe_library`` pentru ``target_keyword``.

    RAG simplu, ca la :func:`retrieve_framework`: suprapunere de jetoane intre
    cuvantul cheie tinta si campurile ``niche``/``format`` ale fiecarei intrari,
    fara embeddings. La egalitate de scor, castiga intrarea activa mai mult timp
    (``days_active_proxy``) — o reclama dovedita e un exemplu mai de incredere.
    Nu ridica eroare la suprapunere zero (un exemplu generic tot ajuta un LLM ca
    ghidaj de ritm/ton); ridica doar daca biblioteca e complet goala.

    Args:
        swipe: Continutul swipe file.
        target_keyword: Cuvantul cheie / nisa tinta a anuntului.
        limit: Numarul maxim de exemple returnate.

    Returns:
        Pana la ``limit`` intrari, ordonate descrescator dupa relevanta.

    Raises:
        SwipeFileError: Daca ``tiktok_swipe_library`` e goala.
    """
    if not swipe.tiktok_swipe_library:
        raise SwipeFileError(
            "tiktok_swipe_library este goala in swipe_file.json - ruleaza "
            "'ingest-tiktok' sau adauga intrari manual"
        )
    keyword_tokens = set(tokenize(target_keyword))
    ranked = sorted(
        swipe.tiktok_swipe_library,
        key=lambda record: (
            _niche_overlap(record, keyword_tokens),
            record.days_active_proxy,
        ),
        reverse=True,
    )
    return ranked[:limit]
