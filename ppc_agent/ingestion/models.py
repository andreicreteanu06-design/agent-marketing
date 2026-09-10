"""Structuri de date tipizate produse de Modulul 1 (context si ingestie)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ppc_agent.texttools import SentimentLabel

MatchType = Literal["broad", "phrase", "exact"]


class PageContext(BaseModel):
    """Structura si mesajele cheie extrase dintr-o pagina de destinatie."""

    url: str
    ok: bool
    status_code: int
    failure_reason: str | None = None
    title: str = ""
    meta_description: str = ""
    h1: list[str] = Field(default_factory=list)
    h2: list[str] = Field(default_factory=list)
    h3: list[str] = Field(default_factory=list)
    cta_texts: list[str] = Field(default_factory=list)
    nav_items: list[str] = Field(default_factory=list)
    usp_candidates: list[str] = Field(default_factory=list)

    @property
    def heading_texts(self) -> list[str]:
        """Toate titlurile H1-H3, in ordine."""
        return [*self.h1, *self.h2, *self.h3]

    @property
    def is_sparse(self) -> bool:
        """Adevarat cand pagina are prea putin continut (probabil randata JS).

        Semnal pentru fallback: titlu foarte scurt si cel mult un heading.
        """
        return self.ok and len(self.heading_texts) <= 1 and len(self.title) < 10

    @classmethod
    def failed(
        cls, url: str, *, status_code: int = 0, reason: str = "fetch_failed"
    ) -> PageContext:
        """Construieste un context pentru o pagina care nu a putut fi obtinuta."""
        return cls(url=url, ok=False, status_code=status_code, failure_reason=reason)


class SeedKeyword(BaseModel):
    """Interogare organica din GSC, folosita ca samanta de cuvant cheie."""

    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    intent_score: float


class ReviewSentiment(BaseModel):
    """O recenzie si scorul ei de sentiment."""

    text: str
    score: float
    label: SentimentLabel


class LocalSignals(BaseModel):
    """Semnale locale despre entitate, din Google Business Profile."""

    name: str
    categories: list[str] = Field(default_factory=list)
    review_count: int = 0
    avg_rating: float = 0.0
    reviews: list[ReviewSentiment] = Field(default_factory=list)

    @property
    def sentiment_mix(self) -> dict[SentimentLabel, int]:
        """Numarul de recenzii pe fiecare eticheta de sentiment."""
        mix: dict[SentimentLabel, int] = {"pozitiv": 0, "neutru": 0, "negativ": 0}
        for review in self.reviews:
            mix[review.label] += 1
        return mix


class ExpandedKeyword(BaseModel):
    """Cuvant cheie rezultat din expansiunea Keyword Planner."""

    keyword: str
    avg_monthly_searches: int
    competition: float
    low_top_bid: Decimal
    high_top_bid: Decimal
    match_type_suggestion: MatchType


class NegativeKeyword(BaseModel):
    """Cuvant cheie negativ generat inainte de lansare."""

    term: str
    reason_code: str
    match_type: MatchType = "broad"
    matched_token: str | None = None


class NegativeKeywordSet(BaseModel):
    """Colectie de cuvinte cheie negative, cu grupare pe motiv."""

    items: list[NegativeKeyword] = Field(default_factory=list)

    def terms(self) -> list[str]:
        """Lista termenilor negativi, in ordinea adaugarii."""
        return [item.term for item in self.items]

    def by_reason(self) -> dict[str, list[NegativeKeyword]]:
        """Gruparea intrarilor pe ``reason_code``."""
        grouped: dict[str, list[NegativeKeyword]] = {}
        for item in self.items:
            grouped.setdefault(item.reason_code, []).append(item)
        return grouped


class IngestionResult(BaseModel):
    """Iesirea completa a Modulului 1 pentru un domeniu."""

    url: str
    page_context: PageContext
    seed_keywords: list[SeedKeyword] = Field(default_factory=list)
    local_signals: LocalSignals | None = None
    expanded_keywords: list[ExpandedKeyword] = Field(default_factory=list)
    negative_keywords: NegativeKeywordSet = Field(default_factory=NegativeKeywordSet)
