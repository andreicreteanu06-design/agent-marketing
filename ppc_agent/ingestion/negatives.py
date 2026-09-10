"""Schela deterministica de cuvinte cheie negative, generata inainte de lansare.

Fara ML si fara aleator: doar potriviri de jetoane si un scor de intentie
comerciala bazat pe lexicon. Fiecare intrare poarta un ``reason_code`` si
jetonul care a declansat-o.
"""

from __future__ import annotations

from ppc_agent.ingestion.models import (
    ExpandedKeyword,
    NegativeKeyword,
    NegativeKeywordSet,
    PageContext,
)
from ppc_agent.texttools import contains_phrase, tokenize

# Jetoane / fraze negative de baza, pe categorii. Acopera RO si EN.
NEGATIVE_TOKENS: dict[str, tuple[str, ...]] = {
    "INFORMATIONAL": (
        "ce este",
        "ce inseamna",
        "cum sa",
        "cum se",
        "ghid",
        "tutorial",
        "definitie",
        "exemplu",
        "model",
        "wiki",
        "what is",
        "how to",
        "meaning",
        "definition",
    ),
    "PRICE_SHOPPER": (
        "gratis",
        "gratuit",
        "ieftin",
        "reducere",
        "cupon",
        "free",
        "cheap",
        "discount",
        "coupon",
    ),
    "JOB_SEEKER": (
        "job",
        "joburi",
        "salariu",
        "cariera",
        "angajare",
        "angajari",
        "jobs",
        "salary",
        "career",
        "hiring",
        "internship",
    ),
    "DIY": (
        "diy",
        "fa singur",
        "sablon",
        "template",
        "in excel",
        "manual",
    ),
}

DEFAULT_INTENT_THRESHOLD = 0.40

_COMMERCIAL_TOKENS: frozenset[str] = frozenset(
    {
        "pret",
        "preturi",
        "tarif",
        "cost",
        "cumpara",
        "comanda",
        "abonament",
        "achizitie",
        "oferta",
        "servicii",
        "consultanta",
        "software",
        "aplicatie",
        "program",
        "platforma",
        "firma",
        "companie",
        "buy",
        "price",
        "pricing",
        "quote",
        "hire",
        "vendor",
        "tool",
        "platform",
    }
)

_INTENT_BASE = 0.45
_INTENT_PER_COMMERCIAL = 0.20
_INTENT_COMMERCIAL_CAP = 0.45
_INTENT_PER_NEGATIVE = 0.25
_INTENT_SINGLE_TOKEN_PENALTY = 0.15


def commercial_intent(keyword: str) -> float:
    """Scor de intentie comerciala pentru un cuvant cheie fara semnal de click, in [0, 1].

    Math: pornind de la ``0.45``:

    - ``+0.20`` pentru fiecare jeton comercial distinct, plafonat la ``+0.45``
    - ``-0.25`` pentru fiecare potrivire cu un jeton negativ de baza
    - ``-0.15`` daca este un singur cuvant (prea larg pentru broad match)

    Rezultatul este taiat la [0, 1] si rotunjit la 4 zecimale.

    Args:
        keyword: Cuvantul cheie evaluat.

    Returns:
        Scorul de intentie comerciala.
    """
    tokens = tokenize(keyword)
    commercial_hits = len(set(tokens) & _COMMERCIAL_TOKENS)
    negative_hits = sum(
        1
        for phrases in NEGATIVE_TOKENS.values()
        for phrase in phrases
        if contains_phrase(keyword, phrase)
    )
    single_token_penalty = _INTENT_SINGLE_TOKEN_PENALTY if len(tokens) <= 1 else 0.0
    raw = (
        _INTENT_BASE
        + min(_INTENT_COMMERCIAL_CAP, _INTENT_PER_COMMERCIAL * commercial_hits)
        - _INTENT_PER_NEGATIVE * negative_hits
        - single_token_penalty
    )
    return round(min(1.0, max(0.0, raw)), 4)


def _match_negative_token(keyword: str) -> tuple[str, str] | None:
    """Prima potrivire (categorie, fraza) cu un jeton negativ de baza, sau ``None``."""
    for category, phrases in NEGATIVE_TOKENS.items():
        for phrase in phrases:
            if contains_phrase(keyword, phrase):
                return category, phrase
    return None


def scaffold_negatives(
    expanded: list[ExpandedKeyword],
    page_context: PageContext,
    competitor_brands: list[str],
    *,
    intent_threshold: float = DEFAULT_INTENT_THRESHOLD,
) -> NegativeKeywordSet:
    """Genereaza cuvinte cheie negative broad match inainte de lansarea campaniei.

    Reguli, in ordine (prima aplicabila stabileste motivul):

    1. ``COMPETITOR_BRAND`` — contine un brand concurent din configuratie
    2. ``TOKEN_<categorie>`` — contine un jeton negativ de baza
    3. ``LOW_COMMERCIAL_INTENT`` — :func:`commercial_intent` sub ``intent_threshold``
       si cuvantul nu apare in H1/H2 ale paginii de destinatie

    Args:
        expanded: Cuvintele cheie candidate din expansiune.
        page_context: Contextul paginii de destinatie (relevanta H1/H2).
        competitor_brands: Branduri concurente din configuratie.
        intent_threshold: Prag sub care intentia comerciala este considerata slaba.

    Returns:
        Setul de cuvinte cheie negative, cu motiv si jeton per intrare.
    """
    heading_blob = " ".join([*page_context.h1, *page_context.h2])
    brands = [brand.strip() for brand in competitor_brands if brand.strip()]
    items: list[NegativeKeyword] = []
    seen: set[str] = set()

    for candidate in expanded:
        keyword = candidate.keyword
        if keyword in seen:
            continue
        seen.add(keyword)

        brand_hit = next(
            (brand for brand in brands if contains_phrase(keyword, brand)), None
        )
        if brand_hit is not None:
            items.append(
                NegativeKeyword(
                    term=keyword,
                    reason_code="COMPETITOR_BRAND",
                    matched_token=brand_hit,
                )
            )
            continue

        token_hit = _match_negative_token(keyword)
        if token_hit is not None:
            category, phrase = token_hit
            items.append(
                NegativeKeyword(
                    term=keyword,
                    reason_code=f"TOKEN_{category}",
                    matched_token=phrase,
                )
            )
            continue

        on_page = contains_phrase(heading_blob, keyword)
        if not on_page and commercial_intent(keyword) < intent_threshold:
            items.append(
                NegativeKeyword(term=keyword, reason_code="LOW_COMMERCIAL_INTENT")
            )

    return NegativeKeywordSet(items=items)
