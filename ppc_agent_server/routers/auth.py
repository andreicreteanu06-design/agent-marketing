"""``POST /api/v1/auth/mcc-connect`` — schimb OAuth pentru Google Ads MCC / Meta / TikTok.

Stub deliberat, ca toate celelalte integrari ``live`` din ``ppc_agent``: niciun
plumbing OAuth real nu exista inca pentru nicio platforma, deci endpoint-ul
ridica ``SetupRequiredError`` (-> 503 prin handler-ul global din ``app.py``) in
loc sa pretinda ca functioneaza.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ppc_agent.errors import SetupRequiredError
from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.models import Tenant
from ppc_agent_server.schemas import McConnectRequest

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/mcc-connect")
def mcc_connect(
    payload: McConnectRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> None:
    """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
    raise SetupRequiredError(
        f"schimbul OAuth pentru '{payload.platform}' nu e inca implementat. "
        "Configureaza credentialele platformei si asteapta integrarea live."
    )
