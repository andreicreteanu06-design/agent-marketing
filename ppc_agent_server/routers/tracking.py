"""``POST /api/v1/tracking/conversion/{client_id}`` — ingestie universala de conversii.

``client_id`` in URL (nu in payload): o sursa terta (Gomag, un provider VoIP)
nu are niciun concept despre ID-ul nostru intern de client — vine din URL-ul de
webhook unic pe care agentia il configureaza in platforma clientului.

Doua chei acceptate:

- **cheia de webhook a clientului** (``whk_...``, ``security.webhook_key``): merge DOAR
  pe webhook-ul acelui client. Pe ea o primeste site-ul clientului - in antetul
  ``Authorization: Bearer whk_...`` sau, pentru platformele care accepta doar un URL
  (Gomag, un call tracker), ca ``?key=whk_...``;
- **cheia agentiei** (``Authorization: Bearer pk_...``), ca restul API-ului: deschide
  toti clientii agentiei, deci nu se da niciodata unui client. ``client_id`` doar
  selecteaza CARE cont al agentiei primeste conversia (``get_owned_client`` - 404).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.schemas import ConversionOutcome
from ppc_agent_server.security import WEBHOOK_KEY_PREFIX, verify_webhook_key
from ppc_agent_server.tracking.adapters import get_adapter
from ppc_agent_server.tracking.errors import TrackingError
from ppc_agent_server.tracking.meta_capi import forward_conversion
from ppc_agent_server.tracking.pipeline import record_conversion
from ppc_agent_server.tracking.platform_conversions import forward_to_platforms

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


def webhook_account(
    client_id: int,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    key: Annotated[str | None, Query(description="cheia de webhook a clientului")] = None,
) -> ClientAccount:
    """Contul care primeste conversia: din cheia lui de webhook sau din cheia agentiei.

    Raises:
        HTTPException: 401 cheie lipsa/invalida (sau cheia altui client); 403 agentie
            suspendata; 404 client care nu apartine agentiei; 503 server fara
            ``JWT_SECRET_KEY`` (cheile de webhook nu se pot verifica).
    """
    bearer = (authorization or "").removeprefix("Bearer ").strip()
    raw = key or bearer
    if not raw.startswith(WEBHOOK_KEY_PREFIX):
        if key:
            raise HTTPException(status_code=401, detail="cheie de webhook invalida")
        return get_owned_client(
            client_id, get_current_tenant(session=session, authorization=authorization), session
        )
    try:
        valid = verify_webhook_key(raw, client_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    account = session.get(ClientAccount, client_id)
    if not valid or account is None:
        raise HTTPException(status_code=401, detail="cheie de webhook invalida pentru acest client")
    tenant = session.get(Tenant, account.tenant_id)
    if tenant is not None and tenant.subscription_status == "suspended":
        raise HTTPException(status_code=403, detail="abonamentul agentiei este suspendat")
    return account


@router.post("/conversion/{client_id}", response_model=ConversionOutcome, status_code=201)
def ingest_conversion(
    raw_payload: dict[str, Any],
    source_platform: Annotated[
        str, Query(description="gomag, call_tracker sau custom_web")
    ],
    account: Annotated[ClientAccount, Depends(webhook_account)],
    session: Annotated[Session, Depends(get_session)],
) -> ConversionOutcome:
    """Normalizeaza, califica si inregistreaza o conversie de la orice sursa.

    Conversiile calificate pleaca apoi la platformele clientului - Meta
    (``tracking/meta_capi.py``), Google Ads, TikTok si ChatGPT
    (``tracking/platform_conversions.py``); un esec acolo nu strica ingestia.

    Raises:
        HTTPException: vezi :func:`webhook_account`; 422 daca ``source_platform``
            e necunoscuta sau payload-ul nu respecta forma asteptata a sursei.
    """
    try:
        adapter = get_adapter(source_platform)
        conversion = adapter.to_standardized(raw_payload, client_id=str(account.id))
    except TrackingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    outcome = record_conversion(session, account, conversion)
    # Si dupa o deduplicare: un webhook retrimis reincearca o trimitere esuata.
    outcome.meta_capi = forward_conversion(session, account, conversion)
    platforms = forward_to_platforms(session, account, conversion)
    outcome.google_ads = platforms.get("google_ads")
    outcome.tiktok = platforms.get("tiktok")
    outcome.chatgpt = platforms.get("chatgpt")
    return outcome
