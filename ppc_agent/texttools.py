"""Utilitare de text partajate: normalizare, tokenizare, potrivire de fraze, sentiment.

Modul frunza — nu depinde de nimic altceva din pachet. Folosit de stratul de
ingestie (Modulul 1) si, ulterior, de alinierea Quality Score (Modulul 3).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

__all__ = [
    "SentimentLabel",
    "contains_phrase",
    "normalize",
    "score_sentiment",
    "tokenize",
]

SentimentLabel = Literal["pozitiv", "neutru", "negativ"]

_WORD_RE = re.compile(r"[a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")

_POSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "bun", "buna", "bune", "excelent", "excelenta", "recomand", "recomandat",
        "minunat", "perfect", "rapid", "profesionist", "profesionisti", "amabil",
        "multumit", "multumita", "super", "prompt", "serios", "calitate",
        "great", "excellent", "recommend", "fast", "friendly", "love", "best",
        "amazing", "helpful", "reliable", "smooth", "wonderful",
    }
)
_NEGATIVE_WORDS: frozenset[str] = frozenset(
    {
        "prost", "proasta", "proaste", "groaznic", "dezamagit", "dezamagita",
        "lent", "scump", "nepoliticos", "evitati", "rau", "teribil", "intarziere",
        "anulat", "jalnic", "mizerie", "nefunctional",
        "bad", "terrible", "slow", "expensive", "rude", "avoid", "worst",
        "disappointed", "awful", "poor", "broken", "horrible",
    }
)

_POSITIVE_THRESHOLD = 0.2
_NEGATIVE_THRESHOLD = -0.2


def normalize(text: str) -> str:
    """Text minuscul, fara diacritice, cu spatiile colapsate.

    Diacriticele romanesti sunt reduse la ASCII (a-breve / a-circumflex / i-circumflex
    -> ``a`` / ``i``, s-virgula -> ``s``, t-virgula -> ``t``) prin descompunere
    Unicode NFKD urmata de eliminarea semnelor combinate.

    Args:
        text: Textul brut.

    Returns:
        Forma normalizata, utila pentru comparatii insensibile la diacritice si caz.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE_RE.sub(" ", without_marks.lower()).strip()


def tokenize(text: str) -> list[str]:
    """Imparte textul in jetoane alfanumerice minuscule, fara diacritice.

    Args:
        text: Textul brut.

    Returns:
        Lista de jetoane (poate fi goala).
    """
    return _WORD_RE.findall(normalize(text))


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Adevarat daca ``phrase`` apare in ``haystack`` ca secventa contigua de jetoane.

    Ambele argumente sunt normalizate inainte de comparatie, deci potrivirea este
    insensibila la diacritice, caz si punctuatie.

    Args:
        haystack: Textul in care se cauta.
        phrase: Fraza cautata (unul sau mai multe cuvinte).

    Returns:
        Rezultatul potrivirii.
    """
    needle = tokenize(phrase)
    if not needle:
        return False
    hay = tokenize(haystack)
    window = len(needle)
    if window > len(hay):
        return False
    return any(hay[i : i + window] == needle for i in range(len(hay) - window + 1))


def score_sentiment(text: str) -> tuple[float, SentimentLabel]:
    """Scor de sentiment lexical, in intervalul [-1, 1].

    Math: fie ``p`` numarul de jetoane pozitive si ``n`` numarul de jetoane
    negative gasite intr-un lexicon RO+EN. Scorul este ``(p - n) / (p + n)``
    cand ``p + n > 0``, altfel ``0``. Eticheta: ``pozitiv`` peste ``0.2``,
    ``negativ`` sub ``-0.2``, ``neutru`` intre.

    Nu trateaza negatia ("nu recomand"); un model real se poate cupla ulterior
    prin aceeasi semnatura.

    Args:
        text: Textul recenziei.

    Returns:
        Perechea ``(scor, eticheta)``.
    """
    tokens = tokenize(text)
    positive = sum(1 for token in tokens if token in _POSITIVE_WORDS)
    negative = sum(1 for token in tokens if token in _NEGATIVE_WORDS)
    total = positive + negative
    score = 0.0 if total == 0 else (positive - negative) / total
    if score > _POSITIVE_THRESHOLD:
        return score, "pozitiv"
    if score < _NEGATIVE_THRESHOLD:
        return score, "negativ"
    return score, "neutru"
