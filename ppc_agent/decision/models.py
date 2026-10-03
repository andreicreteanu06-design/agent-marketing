"""Structuri de date tipizate pentru Modulul 2 (motor matematic de decizie)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

EdgeLabel = Literal["pozitiv", "neutru", "negativ", "date_insuficiente"]
ArmCapacityTier = Literal["micro", "standard", "scale"]


class ArmStats(BaseModel):
    """Performanta istorica a unui "brat" (campanie sau grup de anunturi).

    ``platform`` e ``str`` simplu, nu ``Literal`` — o a patra platforma viitoare
    nu cere sa editezi un tip aici, doar sa o adaugi la sursa (``ProviderFactory``
    + ``run_plan``). Implicit ``"google_ads"`` ca toate bratele existente
    (construite fara acest argument) sa ramana identice.
    """

    arm_id: str
    name: str
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    cost: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")
    platform: str = "google_ads"
    #: Ruleaza acum (Meta: setul are ``effective_status`` ``ACTIVE``). Unul oprit isi
    #: pastreaza istoricul pentru CFO, dar nu mai primeste buget de la Thompson.
    active: bool = True
    #: Bugetul zilnic de acum, cand platforma il raporteaza (Google: bugetul campaniei,
    #: TikTok: al grupului de anunturi). Propunerile de noapte pleaca de la el in pasi.
    daily_budget: Decimal | None = None
    #: De ce bugetul acestui brat nu se poate muta aici (buget partajat intre campanii,
    #: buget pe campanie, buget pe viata, faza de invatare). Gol = se poate muta.
    budget_locked: str = ""

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
    platform: str = "google_ads"
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


class ArmCapacityAdvice(BaseModel):
    """Recomandare: cate brate/variante de creatie poate sustine activ un buget zilnic.

    Motivatie: :class:`~ppc_agent.decision.budget.ThompsonBudgetAllocator` are deja
    un prag minim per brat (``min_arm_daily_spend``, vezi ``budget._apply_floor``)
    sub care dezactiveaza bratele - dar pana acum era un numar static din
    config, fara nicio legatura cu ``target_cpa``. La un buget de 10-25 lei/zi si
    ``target_cpa`` de 100+ lei, un prag static mic nu inseamna nimic: bratele raman
    "finantate" cu sume care nu vor ajunge niciodata la pragul de cheltuiala al
    Gate B (``PAUSE_HARD`` = 2x ``target_cpa``, vezi ``fatigue_monitor.py``) -
    Fatigue Monitor-ul ramane etern in ``CONTINUE`` iar bugetul se scurge fara
    diagnostic. Aceasta structura calculeaza pragul corect, derivat din acelasi
    multiplicator pe care Gate B il foloseste deja (vezi
    :func:`~ppc_agent.decision.budget_strategy.recommend_arm_capacity`).
    """

    daily_budget: Decimal
    target_cpa: Decimal
    target_evaluation_days: float
    recommended_min_arm_daily_spend: Decimal
    recommended_max_concurrent_arms: int
    tier: ArmCapacityTier
    rationale: str


class PlanResult(BaseModel):
    """Iesirea completa a Modulului 2: dimensionare Kelly + alocare buget + atribuire."""

    kelly: KellySizing
    budget_plan: BudgetPlan
    attribution: AttributionResult
    arm_capacity: ArmCapacityAdvice | None = None
    #: Bratele care au intrat in plan (active, cu venitul estimat unde lipsea) - cu
    #: bugetul de acum, din care propunerile pleaca in pasi.
    arms: list[ArmStats] = Field(default_factory=list)


class DailyArmMetric(BaseModel):
    """O singura zi din istoricul de performanta al unui brat.

    Distinct de :class:`ArmStats` (agregat pe toata perioada, fara nicio
    notiune de timp): un forecaster (vezi ``forecasting.py``) are nevoie de o
    serie ordonata in timp, nu de un singur total.
    """

    date: date
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    cost: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")


class ArmForecast(BaseModel):
    """Iesirea unui forecaster (``forecasting.py``): un :class:`ArmStats` PROIECTAT.

    Deliberat acelasi tip ``ArmStats`` ca istoricul brut, nu unul nou:
    ``kelly_sizing.size_daily_budget`` si ``budget.ThompsonBudgetAllocator``
    raman complet neschimbate, primesc ``projected`` exact cum ar primi
    istoricul real - nu conteaza pentru ele daca numerele vin dintr-o proiectie
    sau dintr-un raport brut.
    """

    projected: ArmStats
    conversions_low: float
    conversions_high: float
    method: Literal["trend", "timesfm"]
