"""Structuri de date tipizate pentru Modulul 3 (aliniere algoritmica)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

QsRating = Literal["Low", "Avg", "High"]


class AdGroupInput(BaseModel):
    """Copy-ul propus pentru un grup de anunturi (stand-in pentru iesirea unui LLM)."""

    ad_group_id: str
    name: str
    exact_match_keyword: str
    headlines: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)


class QualityScoreReport(BaseModel):
    """Estimare de Quality Score pentru un grup de anunturi."""

    ad_group_id: str
    name: str
    keyword: str
    score: float
    expected_ctr: QsRating
    ad_relevance: QsRating
    landing_page_experience: QsRating
    keyword_in_h1: bool
    keyword_in_headlines: bool
    flagged: bool
    components: dict[str, float] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)


class AdSet(BaseModel):
    """Un set de reclame Meta."""

    ad_set_id: str
    name: str
    audience_def: str
    weekly_conversions: float = Field(ge=0.0)
    weekly_spend: Decimal = Decimal("0")
    learning_phase: bool = False
    #: Starea bruta din Meta: ``LEARNING`` (invata acum - fara editari) sau
    #: ``LEARNING_LIMITED`` (nu strange destule conversii - bugetul e chiar un remediu).
    learning_status: str = ""
    #: Bugetul zilnic setat acum pe set. ``None`` = bugetul e pe campanie (CBO) sau
    #: necunoscut - atunci agentul nu propune buget pe set.
    daily_budget: Decimal | None = None


class AdSetMerge(BaseModel):
    """O propunere de consolidare a mai multor seturi de reclame intr-unul singur."""

    merged_id: str
    source_ids: list[str]
    projected_weekly_conversions: float
    clears_threshold: bool
    learning_exit_days: float | None = None
    warnings: list[str] = Field(default_factory=list)


class LiquidityPlan(BaseModel):
    """Planul de lichiditate algoritmica pentru un cont Meta."""

    target_weekly_conversions: int
    merges: list[AdSetMerge] = Field(default_factory=list)
    untouched_ids: list[str] = Field(default_factory=list)
    recommend_cbo: bool = False
    warnings: list[str] = Field(default_factory=list)


class AlignmentResult(BaseModel):
    """Iesirea completa a Modulului 3: rapoarte Quality Score + plan de lichiditate Meta."""

    quality_score_reports: list[QualityScoreReport] = Field(default_factory=list)
    liquidity_plan: LiquidityPlan
    #: Seturile citite din cont: bugetul de acum si faza de invatare, pentru
    #: limitarea pasului de buget (``guardrails.pipeline.build_proposed_changes``).
    ad_sets: list[AdSet] = Field(default_factory=list)
