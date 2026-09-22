"""Scheme Pydantic pentru request/response API.

Distincte deliberat de modelele SQLModel (tabele) din ``models.py`` — API-ul nu
expune direct structura interna a bazei de date (id-uri interne, campuri de
audit) si poate evolua independent de schema DB.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ppc_agent.campaign_objective import CampaignObjective

AdPlatform = Literal["google", "tiktok"]
McConnectPlatform = Literal["google_ads", "meta", "tiktok_ads"]
JobStatusLabel = Literal["queued", "running", "success", "failed"]


# --- Clienti gestionati ---


class ClientAccountCreate(BaseModel):
    """Corpul cererii ``POST /api/v1/clients``."""

    name: str
    target_domain: str = ""
    geo: str = "RO"
    language: str = "ro"
    google_ads_customer_id: str = ""
    meta_ad_account_id: str = ""
    tiktok_advertiser_id: str = ""
    max_daily_spend: Decimal = Decimal("50.00")
    default_lead_value: Decimal = Decimal("300.00")
    objective: CampaignObjective = CampaignObjective.LEAD_GEN


class ClientAccountUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/clients/{id}`` - doar campurile trimise se schimba.

    Motivatie: ``default_lead_value`` (proxy-ul de valoare pentru lead-uri) e o
    estimare initiala a agentiei - fara o cale de corectare dupa ce se afla rata
    reala de inchidere a vanzarilor, orice eroare initiala ramane permanenta in
    calculele de ROAS/CPA. La fel pentru ``max_daily_spend``/``objective``, care
    se pot schimba pe parcursul relatiei cu clientul.
    """

    name: str | None = None
    target_domain: str | None = None
    geo: str | None = None
    language: str | None = None
    google_ads_customer_id: str | None = None
    meta_ad_account_id: str | None = None
    tiktok_advertiser_id: str | None = None
    max_daily_spend: Decimal | None = Field(default=None, gt=0)
    default_lead_value: Decimal | None = Field(default=None, gt=0)
    objective: CampaignObjective | None = None


class ClientAccountRead(BaseModel):
    """Randul ``ClientAccount``, forma expusa prin API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_domain: str
    geo: str
    language: str
    google_ads_customer_id: str
    meta_ad_account_id: str
    tiktok_advertiser_id: str
    max_daily_spend: Decimal
    default_lead_value: Decimal
    objective: CampaignObjective
    created_at: datetime


# --- Job-uri (plan / copy / creative) ---


class PlanJobRequest(BaseModel):
    client_id: int


class CopyJobRequest(BaseModel):
    client_id: int
    keyword: str
    usp: str
    trigger: str = "aida"
    platform: AdPlatform = "google"


class CreativeJobRequest(BaseModel):
    client_id: int
    keyword: str
    broll_path: str
    trigger: str = "aida"
    usp: str | None = None
    platform: AdPlatform = "google"


class JobAccepted(BaseModel):
    """Raspunsul imediat la dispecerizarea unui job — 202, nu rezultatul final."""

    task_id: str
    status: JobStatusLabel = "queued"


class JobStatusResponse(BaseModel):
    """Raspunsul ``GET /api/v1/jobs/{task_id}``."""

    task_id: str
    status: JobStatusLabel
    result: dict[str, Any] | None = None
    error: str | None = None


# --- Propuneri (poarta HITL) ---


class ProposedChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_account_id: int
    op: str
    resource: str
    resource_type: str
    projected_daily_spend: Decimal
    rationale: str
    source_module: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class ExecuteProposalRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/proposals/{id}/execute``.

    ``confirm`` implicit ``False`` — poarta HITL: fara confirmare explicita,
    nimic nu se executa (la fel ca ``execute --confirm`` in CLI).
    """

    confirm: bool = False


# --- Auth (schimb OAuth) ---


# --- Autentificare client (self-service, distinct de cheia API de agentie) ---


class ClientSignupRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/signup`` - creeaza ClientAccount + ClientUser."""

    name: str
    email: str
    password: str = Field(min_length=8)


class ClientLoginRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/login``."""

    email: str
    password: str


class ClientTokenResponse(BaseModel):
    """Raspunsul la signup/login - token JWT de folosit ca ``Authorization: Bearer``."""

    access_token: str
    token_type: str = "bearer"


class ClientUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    client_account_id: int
    created_at: datetime


class ClientMeResponse(BaseModel):
    """Raspunsul ``GET /api/v1/me`` - identitatea + contul clientului autentificat.

    ``*_connected`` - DOAR daca secretul e prezent (criptat), niciodata
    valoarea - interfata poate arata "deja conectat" fara sa expuna nimic.
    """

    user: ClientUserRead
    account: ClientAccountRead
    google_ads_connected: bool
    meta_connected: bool
    tiktok_connected: bool
    chatgpt_connected: bool


class ClientCredentialsUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/me/credentials``.

    Doar campurile trimise se cripteaza si se salveaza (acelasi pattern ca
    ``ClientAccountUpdate``) - niciun camp nu e obligatoriu, clientul isi
    conecteaza conturile pe rand, pe masura ce le are.

    ``chatgpt_ads_api_key`` alimenteaza ``ClientAccount.chatgpt_ads_api_key_enc``
    (vezi models.py) - folosit azi doar de stocare; ``LiveGenerativeEngineProvider``
    (ppc_agent/providers/live/__init__.py) ramane stub pana la acces de
    partener OpenAI aprobat, deci cheia nu declanseaza inca niciun apel real.
    """

    google_ads_refresh_token: str | None = None
    meta_access_token: str | None = None
    tiktok_access_token: str | None = None
    chatgpt_ads_api_key: str | None = None


class ClientCredentialsUpdateResponse(BaseModel):
    """Raspunsul la actualizarea de credentiale - NICIODATA valorile, nici criptate."""

    updated_fields: list[str]


# --- Urmarire conversii ---


class ConversionOutcome(BaseModel):
    """Raspunsul ``POST /api/v1/tracking/conversion/{client_id}``."""

    event_id: str
    qualified: bool
    reason: str | None = None
    deduplicated: bool = False


class McConnectRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/auth/mcc-connect``.

    Stub deliberat (ca toti clientii ``live`` din ``ppc_agent``): niciun schimb
    OAuth real nu are loc inca — endpoint-ul valideaza forma cererii si ridica
    ``SetupRequiredError`` (-> 503) pana la integrarea reala.
    """

    platform: McConnectPlatform
    authorization_code: str
