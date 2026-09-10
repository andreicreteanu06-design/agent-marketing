"""Structuri de date tipizate pentru Modulul 2 (motor matematic de decizie)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

EdgeLabel = Literal["pozitiv", "neutru", "negativ", "date_insuficiente"]


class ArmStats(BaseModel):
    """Performanta istorica a unui "brat" (campanie sau grup de anunturi)."""

    arm_id: str
    name: str
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    cost: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")

    @property
    def observed_cvr(self) -> float:
        """Rata de conversie observata (0 daca nu exista click-uri)."""
        return self.conversions / self.clicks if self.clicks else 0.0

    @property
    def roas(self) -> float:
        """Return on ad spend (venit / cost); 0 daca nu exista cost."""
        return float(self.revenue / self.cost) if self.cost > 0 else 0.0


class BudgetAllocation(BaseModel):
    """Bugetul zilnic alocat unui brat, plus semnalele care au dus la el."""

    arm_id: str
    name: str
    win_probability: float
    final_share: float
    daily_budget: Decimal
    note: str | None = None


class BudgetPlan(BaseModel):
    """Rezultatul alocarii Thompson Sampling pentru o zi."""

    daily_budget: Decimal
    total_allocated: Decimal
    n_samples: int
    seed: int | None
    allocations: list[BudgetAllocation] = Field(default_factory=list)


class ChannelAttribution(BaseModel):
    """Atribuirea pentru un canal: efect de eliminare plus conversii Markov si last-click."""

    channel: str
    removal_effect: float
    markov_conversions: float
    last_click_conversions: float


class AttributionResult(BaseModel):
    """Rezultatul atribuirii Markov pe un set de parcursuri."""

    total_conversions: float
    base_conversion_probability: float
    channels: list[ChannelAttribution] = Field(default_factory=list)


class KellySizing(BaseModel):
    """Rezultatul dimensionarii Kelly a plafonului zilnic absolut."""

    smoothed_cvr: float
    account_roas: float
    win_prob: float
    roas_odds: float
    kelly_fraction: float
    multiplier: float
    baseline_cap: Decimal
    sized_daily_cap: Decimal
    hard_ceiling: Decimal
    edge: EdgeLabel
    rationale: str


class PlanResult(BaseModel):
    """Iesirea completa a Modulului 2: dimensionare Kelly + alocare buget + atribuire."""

    kelly: KellySizing
    budget_plan: BudgetPlan
    attribution: AttributionResult
