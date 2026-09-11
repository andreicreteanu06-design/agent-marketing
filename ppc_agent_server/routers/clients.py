"""``POST /api/v1/clients`` — inregistreaza un cont de reclame gestionat de agentie."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.schemas import ClientAccountCreate, ClientAccountRead

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
