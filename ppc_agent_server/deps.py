"""Dependinte FastAPI partajate intre routere (dincolo de ``auth.get_current_tenant``)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session

from ppc_agent_server.models import ClientAccount, Tenant


def get_owned_client(client_id: int, tenant: Tenant, session: Session) -> ClientAccount:
    """Clientul ``client_id``, daca apartine ``tenant`` — altfel 404.

    404 (nu 403) deliberat: nu confirmam catre un apelant neautorizat ca
    ID-ul exista dar apartine altcuiva — acelasi raspuns pentru "nu exista" si
    "nu e al tau".
    """
    account = session.get(ClientAccount, client_id)
    if account is None or account.tenant_id != tenant.id:
        raise HTTPException(
            status_code=404, detail="clientul nu exista sau nu apartine agentiei"
        )
    return account
