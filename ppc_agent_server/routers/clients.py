"""``/api/v1/clients`` — CRUD pentru conturile de reclame gestionate de agentie,
plus ``GET .../report`` (date structurate; randarea vizuala/HTML ramane pentru mai tarziu)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.reporting.builder import build_client_report
from ppc_agent_server.reporting.models import ClientReport
from ppc_agent_server.routers.client_auth import economics_read, get_geocoder, update_economics
from ppc_agent_server.schemas import (
    ClientAccountCreate,
    ClientAccountRead,
    ClientAccountUpdate,
    ClientEconomicsRead,
    ClientEconomicsUpdate,
)
from ppc_agent_server.security import webhook_key
from ppc_agent_server.services.geocoding import Geocoder

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@router.post("", response_model=ClientAccountRead, status_code=201)
def create_client(
    payload: ClientAccountCreate,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientAccount:
    """Inregistreaza un client nou pentru agentia autentificata."""
    assert tenant.id is not None  # persistat deja de get_current_tenant
    account = ClientAccount(tenant_id=tenant.id, **payload.model_dump())
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.get("", response_model=list[ClientAccountRead])
def list_clients(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ClientAccount]:
    """Toti clientii agentiei autentificate."""
    return list(
        session.exec(select(ClientAccount).where(ClientAccount.tenant_id == tenant.id)).all()
    )


@router.get("/{client_id}", response_model=ClientAccountRead)
def get_client(
    client_id: int,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientAccount:
    """Un client al agentiei autentificate."""
    return get_owned_client(client_id, tenant, session)


@router.patch("/{client_id}", response_model=ClientAccountRead)
def update_client(
    client_id: int,
    payload: ClientAccountUpdate,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientAccount:
    """Actualizeaza doar campurile trimise (restul raman neschimbate).

    Motivatie principala: corectarea ``default_lead_value`` dupa ce agentia
    afla rata reala de inchidere a vanzarilor (vezi ``ClientAccountUpdate``).
    """
    account = get_owned_client(client_id, tenant, session)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(account, field, value)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.get("/{client_id}/webhook-key")
def get_client_webhook_key(
    client_id: int,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    """Cheia de webhook a clientului: pe ea o primeste site-ul lui, nu cheia agentiei.

    Merge doar pe ``/api/v1/tracking/conversion/{client_id}`` - vezi
    ``docs/ghid-tracking-clienti.md``.

    Raises:
        HTTPException: 404 client care nu e al agentiei; 503 server fara ``JWT_SECRET_KEY``.
    """
    account = get_owned_client(client_id, tenant, session)
    try:
        key = webhook_key(account.id or 0)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"key": key, "webhook_path": f"/api/v1/tracking/conversion/{account.id}"}


@router.get("/{client_id}/economics", response_model=ClientEconomicsRead)
def get_client_economics(
    client_id: int,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientEconomicsRead:
    """Costurile si zona clientului, cu pragurile calculate de consiliu."""
    return economics_read(get_owned_client(client_id, tenant, session))


@router.put("/{client_id}/economics", response_model=ClientEconomicsRead)
def update_client_economics(
    client_id: int,
    payload: ClientEconomicsUpdate,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
    geocoder: Annotated[Geocoder, Depends(get_geocoder)],
) -> ClientEconomicsRead:
    """Agentia completeaza costurile si zona in locul clientului (ex. la onboarding)."""
    account = get_owned_client(client_id, tenant, session)
    return update_economics(session, account, payload, geocoder)


@router.get("/{client_id}/report", response_model=ClientReport)
def get_client_report(
    client_id: int,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientReport:
    """Raportul structurat (JSON) - date + narativa in limbaj simplu, fara jargon.

    Randarea vizuala (HTML/PDF, de aratat direct unui client) ramane pentru o
    sesiune viitoare - acesta e doar stratul de date.
    """
    account = get_owned_client(client_id, tenant, session)
    return build_client_report(session, account)
