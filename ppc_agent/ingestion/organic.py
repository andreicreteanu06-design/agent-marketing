"""Fuziunea datelor organice: GSC (interogari) plus GBP (semnale locale)."""

from __future__ import annotations

import pandas as pd

from ppc_agent.ingestion.models import LocalSignals, ReviewSentiment, SeedKeyword
from ppc_agent.texttools import SentimentLabel, contains_phrase

_COMMERCIAL_HINTS: tuple[str, ...] = (
    "pret",
    "tarif",
    "oferta",
    "cumpara",
    "comanda",
    "abonament",
    "servicii",
    "firma",
    "aproape de mine",
    "near me",
    "software",
    "aplicatie",
    "program",
)
_NON_COMMERCIAL_HINTS: tuple[str, ...] = (
    "ce este",
    "cum",
    "ghid",
    "tutorial",
    "model",
    "exemplu",
    "definitie",
    "curs",
    "gratis",
    "gratuit",
    "job",
    "joburi",
    "salariu",
    "cariera",
    "angajari",
)

_CTR_SATURATION = 0.1


def intent_score(query: str, position: float, ctr: float) -> float:
    """Scor de intentie comerciala pentru o interogare organica, in [0, 1].

    Math: media ponderata a trei factori normalizati:

    - ``poz``  = ``max(0, (11 - min(position, 11)) / 10)`` — pozitie mai buna, scor mai mare
    - ``ctr_f`` = ``min(ctr / 0.1, 1)`` — CTR peste 10% satureaza la 1
    - ``term`` = ``clamp(0.5 + 0.5*[termen comercial] - 0.5*[termen non-comercial], 0, 1)``

    Scor final = ``0.5*poz + 0.3*ctr_f + 0.2*term``, rotunjit la 4 zecimale si
    taiat la intervalul [0, 1].

    Args:
        query: Textul interogarii.
        position: Pozitia medie in GSC.
        ctr: Rata de click, ca fractie (0-1).

    Returns:
        Scorul de intentie.
    """
    pos_factor = max(0.0, (11.0 - min(position, 11.0)) / 10.0)
    ctr_factor = min(ctr / _CTR_SATURATION, 1.0)
    term_delta = 0.0
    if any(contains_phrase(query, hint) for hint in _COMMERCIAL_HINTS):
        term_delta += 0.5
    if any(contains_phrase(query, hint) for hint in _NON_COMMERCIAL_HINTS):
        term_delta -= 0.5
    term_factor = min(1.0, max(0.0, 0.5 + term_delta))
    score = 0.5 * pos_factor + 0.3 * ctr_factor + 0.2 * term_factor
    return round(min(1.0, max(0.0, score)), 4)


def to_seed_keywords(
    frame: pd.DataFrame, min_impressions: int = 100
) -> list[SeedKeyword]:
    """Filtreaza interogarile GSC si le converteste in seminte tipizate.

    Pastreaza doar randurile cu ``impressions`` *strict mai mare* decat
    ``min_impressions`` — pragul in sine este exclus (100 -> exclus, 101 -> inclus).
    Ataseaza un :func:`intent_score` si sorteaza descrescator dupa el.

    Args:
        frame: DataFrame GSC cu coloanele query/clicks/impressions/ctr/position.
        min_impressions: Prag de afisari; randul cu exact aceasta valoare este exclus.

    Returns:
        Lista de :class:`SeedKeyword`, sortata dupa ``intent_score`` descrescator.
    """
    seeds: list[SeedKeyword] = []
    for record in frame.to_dict(orient="records"):
        impressions = int(record["impressions"])
        if impressions <= min_impressions:
            continue
        query = str(record["query"])
        position = float(record["position"])
        ctr = float(record["ctr"])
        seeds.append(
            SeedKeyword(
                query=query,
                clicks=int(record["clicks"]),
                impressions=impressions,
                ctr=ctr,
                position=position,
                intent_score=intent_score(query, position, ctr),
            )
        )
    seeds.sort(key=lambda seed: seed.intent_score, reverse=True)
    return seeds


def _as_label(value: object) -> SentimentLabel:
    if value == "pozitiv":
        return "pozitiv"
    if value == "negativ":
        return "negativ"
    return "neutru"


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def to_local_signals(raw: dict[str, object]) -> LocalSignals:
    """Converteste dictionarul GBP brut intr-un :class:`LocalSignals` tipizat."""
    reviews: list[ReviewSentiment] = []
    raw_reviews = raw.get("reviews", [])
    if isinstance(raw_reviews, list):
        for entry in raw_reviews:
            if isinstance(entry, dict):
                reviews.append(
                    ReviewSentiment(
                        text=str(entry.get("text", "")),
                        score=_as_float(entry.get("score")),
                        label=_as_label(entry.get("label")),
                    )
                )

    raw_categories = raw.get("categories", [])
    categories = (
        [str(item) for item in raw_categories]
        if isinstance(raw_categories, list)
        else []
    )

    return LocalSignals(
        name=str(raw.get("name", "")),
        categories=categories,
        review_count=int(_as_float(raw.get("review_count"))),
        avg_rating=_as_float(raw.get("avg_rating")),
        reviews=reviews,
    )
