"""Scheme Pydantic pentru request/response API.

Distincte deliberat de modelele SQLModel (tabele) din ``models.py`` — API-ul nu
expune direct structura interna a bazei de date (id-uri interne, campuri de
audit) si poate evolua independent de schema DB.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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
