"""Schema relationala a serverului: Tenant -> ClientAccount -> (ProposedChange,
AdQueueItem, CreativeArtifact).

Inlocuieste fisierele JSON locale ale CLI-ului (``proposed_changes_*.json``,
``proposed_ads_queue.json``, ``creative_output/``) cu randuri persistente,
per agentie si per cont gestionat.

DELIBERAT fara ``from __future__ import annotations`` (singurul fisier din
proiect fara el) — limitare cunoscuta SQLModel: adnotarile devin string-uri
lazy (PEP 563), iar rezolverul de relatii al SQLAlchemy nu le mai poate parsa
corect (``list["ClientAccount"]`` ajunge sa fie tratat ca text literal
``"list['ClientAccount']"`` in loc de tipul generic), ceea ce crapa la runtime
cu ``InvalidRequestError``. Referintele catre clase definite mai jos in fisier
raman ghilimele native (forward refs Python obisnuite), nu PEP 563.
"""

import enum
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Column, Numeric
from sqlmodel import Field, Relationship, SQLModel

from ppc_agent.campaign_objective import CampaignObjective


def _money_column() -> Column[Decimal]:
    """``Numeric(10, 2)`` explicit pe fiecare camp banesc: fara scala explicita,
    SQLModel infera un ``sa.Numeric()`` gol, iar SQLite/SQLAlchemy pot intoarce
    ``Decimal`` cu 10 zecimale in loc de 2 la citire (vazut real: "75.0000000000"
    in loc de "75.00"). ``nullable=False`` explicit — un ``sa_column`` custom
    ocoleste inferenta normala de nullability a SQLModel din adnotarea de tip.
    O functie (nu o singura instanta Column module-level) pentru ca fiecare
    coloana are nevoie de propriul ei obiect Column — SQLAlchemy nu permite
    refolosirea aceluiasi Column pe mai multe tabele."""
    return Column(Numeric(10, 2), nullable=False)


class SubscriptionStatus(enum.StrEnum):
    """SQLModel nu mapeaza ``Literal[...]`` la o coloana SQL — doar ``Enum``
    (vezi ``issubclass()`` in ``sqlmodel.main.get_sqlalchemy_type``) — de-asta
    aceste campuri de stare folosesc ``enum.StrEnum``, ca ``ProviderMode`` din
    ``ppc_agent.config`` (nu ``class X(str, enum.Enum)`` — ruff UP042)."""

    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class ChangeOp(enum.StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    PAUSE = "PAUSE"


class ChangeStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class AdQueueStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Platform(enum.StrEnum):
    GOOGLE = "google"
    TIKTOK = "tiktok"


class ConversionEventType(enum.StrEnum):
    PURCHASE = "purchase"
    LEAD = "lead"
    PHONE_CALL = "phone_call"
    CONTACT = "contact"


class AdFatiguePlatform(enum.StrEnum):
    """Platforma pe care ruleaza anuntul urmarit de monitorul de oboseala.

    Distinct de :class:`Platform` (folosit de ``AdQueueItem``/``CreativeArtifact``
    pentru creatie, doar Google/TikTok azi) — aici sunt cele 3 platforme pe care
    ``ppc_agent.decision.fatigue_monitor`` le intelege, Meta inclus."""

    META = "meta"
    TIKTOK = "tiktok"
    GOOGLE = "google"


class AdLifecycleStatus(enum.StrEnum):
    NEW = "new"
    PROFITABLE = "profitable"
    FATIGUED = "fatigued"


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Tenant(SQLModel, table=True):
    """O agentie: cont, cheie API (doar hash-ul se stocheaza), abonament."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    api_key_hash: str = Field(unique=True, index=True)
    subscription_status: SubscriptionStatus = SubscriptionStatus.TRIAL
    created_at: datetime = Field(default_factory=_now)

    client_accounts: list["ClientAccount"] = Relationship(back_populates="tenant")


class ClientAccount(SQLModel, table=True):
    """Un cont de reclame gestionat de o agentie (client-ul agentiei)."""

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    name: str
    target_domain: str = ""
    geo: str = "RO"
    language: str = "ro"

    google_ads_customer_id: str = ""
    meta_ad_account_id: str = ""
    tiktok_advertiser_id: str = ""

    max_daily_spend: Decimal = Field(default=Decimal("50.00"), sa_column=_money_column())
    # Valoare proxy pentru conversii "lead"/"phone_call" fara valoare explicita
    # (vezi ppc_agent_server.tracking.qualification.ConversionQualifier).
    default_lead_value: Decimal = Field(default=Decimal("300.00"), sa_column=_money_column())
    # Niciodata ghicit - citit de RAG-ul de copy, payload-ul Meta si calificarea
    # conversiilor (vezi ppc_agent.campaign_objective). Implicit LEAD_GEN: pastreaza
    # comportamentul deja existent al randurilor vechi de ConversionEvent (fallback
    # pe default_lead_value pentru orice conversie fara valoare explicita).
    objective: CampaignObjective = CampaignObjective.LEAD_GEN
    created_at: datetime = Field(default_factory=_now)

    tenant: Tenant = Relationship(back_populates="client_accounts")
    proposed_changes: list["ProposedChange"] = Relationship(back_populates="client_account")
    ad_queue_items: list["AdQueueItem"] = Relationship(back_populates="client_account")
    creative_artifacts: list["CreativeArtifact"] = Relationship(back_populates="client_account")
    conversion_events: list["ConversionEvent"] = Relationship(back_populates="client_account")
    ad_performance_records: list["AdPerformanceRecord"] = Relationship(
        back_populates="client_account"
    )


class ProposedChange(SQLModel, table=True):
    """Echivalentul DB al ``ppc_agent.guardrails.models.ProposedChange``.

    Aceeasi forma (``op``/``resource``/``resource_type``/``rationale``/
    ``source_module``), plus ``status`` — poarta HITL traieste in tranzitia
    ``pending`` -> ``approved``/``rejected`` -> ``executed``, nu intr-un fisier.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    op: ChangeOp
    resource: str
    resource_type: str
    before: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    projected_daily_spend: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    rationale: str
    source_module: str

    status: ChangeStatus = ChangeStatus.PENDING
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
    decided_by: str | None = None

    client_account: ClientAccount = Relationship(back_populates="proposed_changes")


class AdQueueItem(SQLModel, table=True):
    """Echivalentul DB al ``proposed_ads_queue.json`` — un anunt in asteptare.

    ``ad_copy`` e JSON, nu coloane fixe: schema difera intre Google (``AdCopy``,
    3 campuri) si TikTok (``TikTokAdCopy``, 6 campuri, ``text_overlay`` e lista) —
    aceeasi eterogenitate pe care ``TikTokAdCopy.as_dict()`` o trateaza deja
    (``dict[str, Any]``) in modulul copywriter.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    platform: Platform = Platform.GOOGLE
    target_keyword: str
    emotion_trigger: str
    product_usp: str
    ad_copy: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    status: AdQueueStatus = AdQueueStatus.PENDING_REVIEW
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="ad_queue_items")


class CreativeArtifact(SQLModel, table=True):
    """Urmareste o creatie generata (voce + video) — echivalentul ``creative_output/``."""

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    platform: Platform = Platform.GOOGLE
    keyword: str
    wav_path: str
    mp4_path: str
    duration_seconds: float
    manifest: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="creative_artifacts")


class ConversionEvent(SQLModel, table=True):
    """O conversie normalizata, cu PII deja hash-uit (SHA-256) - niciodata in clar.

    Pastrata pentru audit + deduplicare (``event_id`` unic per client) - NU e
    sursa de adevar pentru starea unui anunt (asta e ``AdPerformanceRecord``,
    actualizat doar cand conversia e calificata si are un ``ad_id`` cunoscut).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    event_id: str = Field(unique=True, index=True)
    event_type: ConversionEventType
    value: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    currency: str = "RON"
    email_sha256: str | None = None
    phone_sha256: str | None = None
    source_platform: str
    lead_status: str | None = None
    call_duration_seconds: int | None = None
    ad_id: str | None = Field(default=None, index=True)

    qualified: bool
    disqualification_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="conversion_events")


class AdPerformanceRecord(SQLModel, table=True):
    """Rollup persistat per (client, anunt) - alimenteaza direct AdPerformanceState.

    Doar campurile pe care o conversie le poate schimba legitim
    (``conversions``, ``revenue``) se actualizeaza la fiecare conversie
    CALIFICATA cu ``ad_id`` cunoscut — restul (impressions/clicks/ctr/spend si
    variantele lor de baza) raman la valoarea cu care randul a fost creat pana
    cand un proces separat de sincronizare cu platformele de reclame le
    actualizeaza; acel proces e in afara scopului acestui task (semnalat
    explicit, ca OAuth-ul real sau upload-ul de b-roll in alte module).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    ad_id: str = Field(index=True)

    platform: AdFatiguePlatform
    status: AdLifecycleStatus = AdLifecycleStatus.NEW
    launch_time: datetime

    spend: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    target_cpa: Decimal = Field(sa_column=_money_column())
    conversions: int = Field(default=0, ge=0)
    revenue: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    ctr: float = 0.0
    account_median_ctr: float = 0.0
    frequency_7d: float = 0.0
    six_second_view_rate: float = 0.0
    cpa_3d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    cpa_baseline_14d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    bad_days_last_5: int = Field(default=0, ge=0)
    ctr_3d: float = 0.0
    ctr_baseline_14d: float = 0.0
    ctr_baseline_7d: float = 0.0
    cpa_baseline_7d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    six_second_view_rate_baseline: float = 0.0
    bad_days_last_3: int = Field(default=0, ge=0)

    updated_at: datetime = Field(default_factory=_now)

    @property
    def roas(self) -> float:
        """Return on ad spend (venit / cost); 0 daca nu exista cost (ca ArmStats.roas)."""
        return float(self.revenue / self.spend) if self.spend > 0 else 0.0

    client_account: ClientAccount = Relationship(back_populates="ad_performance_records")
