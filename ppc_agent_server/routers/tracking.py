"""``POST /api/v1/tracking/conversion/{client_id}`` — ingestie universala de conversii.

``client_id`` in URL (nu in payload): o sursa terta (Gomag, un provider VoIP)
nu are niciun concept despre ID-ul nostru intern de client — vine din URL-ul de
webhook unic pe care agentia il configureaza in platforma clientului, la fel ca
un webhook secret. Ruta ramane totusi autentificata la nivel de agentie
(``Authorization: Bearer <cheie>``, ca restul API-ului) — ``client_id`` doar
selecteaza CARE cont al agentiei autentificate primeste conversia
(``get_owned_client`` — 404 daca nu-i apartine).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.models import Tenant
from ppc_agent_server.schemas import ConversionOutcome
from ppc_agent_server.tracking.adapters import get_adapter
from ppc_agent_server.tracking.errors import TrackingError
from ppc_agent_server.tracking.meta_capi import forward_conversion
from ppc_agent_server.tracking.pipeline import record_conversion

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


@router.post("/conversion/{client_id}", response_model=ConversionOutcome, status_code=201)
def ingest_conversion(
    client_id: int,
    raw_payload: dict[str, Any],
    source_platform: Annotated[
        str, Query(description="gomag, call_tracker sau custom_web")
    ],
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ConversionOutcome:
    """Normalizeaza, califica si inregistreaza o conversie de la orice sursa.

    Conversiile calificate pleaca apoi si la Meta Conversions API, daca clientul
    are pixel (vezi ``tracking/meta_capi.py``) - un esec acolo nu strica ingestia.

    Raises:
        HTTPException: 404 daca ``client_id`` nu apartine agentiei
            autentificate; 422 daca ``source_platform`` e necunoscuta sau
            payload-ul nu respecta forma asteptata a sursei.
    """
    account = get_owned_client(client_id, tenant, session)
    try:
        adapter = get_adapter(source_platform)
        conversion = adapter.to_standardized(raw_payload, client_id=str(client_id))
    except TrackingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    outcome = record_conversion(session, account, conversion)
    # Si dupa o deduplicare: un webhook retrimis reincearca o trimitere esuata.
    outcome.meta_capi = forward_conversion(session, account, conversion)
    return outcome
