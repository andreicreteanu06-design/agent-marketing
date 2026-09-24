"""``GET /api/v1/seo/intelligence`` - pagina "Trafic & Pozitii" a clientului.

Triangularea GA4 + Search Console + Keyword Planner intr-un singur raspuns:
serie de timp pentru grafic, clasamentul cuvintelor si recomandarile. Logica e
in ``seo_geo_agent/services/intelligence.py``; aici doar autentificarea, contul
si sursele lui (vezi ``ppc_agent_server/seo_intelligence.py``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from ppc_agent_server.db import get_session
from ppc_agent_server.google_integrations import GoogleOAuthClient
from ppc_agent_server.models import ClientAccount, ClientUser
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.routers.integrations import get_google_oauth_client, get_google_transport
from ppc_agent_server.seo_intelligence import build_sources
from seo_geo_agent.services.intelligence import SEOIntelligencePayload, Window, build_intelligence

router = APIRouter(prefix="/api/v1/seo", tags=["seo-intelligence"])

#: Perioadele din interfata (7 zile, 4 saptamani, 3 luni).
ALLOWED_DAYS = (7, 28, 90)
#: Search Console publica datele finale cu ~2-3 zile intarziere; GA4 e aliniat
#: la aceeasi zi, ca pe grafic sesiunile si clicurile sa fie ale acelorasi zile.
DATA_LAG_DAYS = 3


def get_today() -> date:
    """Dependinta: ziua curenta (UTC). Injectabila, ca testele sa fie deterministe."""
    return datetime.now(tz=UTC).date()


@router.get("/intelligence", response_model=SEOIntelligencePayload)
def read_seo_intelligence(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    oauth: Annotated[GoogleOAuthClient | None, Depends(get_google_oauth_client)],
    transport: Annotated[httpx.BaseTransport | None, Depends(get_google_transport)],
    today: Annotated[date, Depends(get_today)],
    days: Annotated[int, Query(description="Lungimea perioadei: 7, 28 sau 90 de zile.")] = 28,
) -> SEOIntelligencePayload:
    """Traficul (GA4), pozitiile (Search Console) si recomandarile perioadei.

    Sursele neconectate apar ca date demonstrative (``is_demo``); o sursa
    conectata care pica ramane goala, cu motivul in ``data_gaps``.
    """
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="Perioada poate fi de 7, 28 sau 90 de zile.")
    account = session.get(ClientAccount, user.client_account_id)
    assert account is not None  # garantat de FK, creat impreuna la signup
    sources = build_sources(account, oauth=oauth, transport=transport, today=today)
    window = Window.ending(today - timedelta(days=DATA_LAG_DAYS), days)
    domain = account.target_domain.removeprefix("https://").removeprefix("http://")
    return build_intelligence(sources, domain=domain, window=window)
