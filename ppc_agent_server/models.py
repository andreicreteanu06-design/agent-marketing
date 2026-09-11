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
    created_at: datetime = Field(default_factory=_now)

    tenant: Tenant = Relationship(back_populates="client_accounts")
    proposed_changes: list["ProposedChange"] = Relationship(back_populates="client_account")
    ad_queue_items: list["AdQueueItem"] = Relationship(back_populates="client_account")
    creative_artifacts: list["CreativeArtifact"] = Relationship(back_populates="client_account")


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
