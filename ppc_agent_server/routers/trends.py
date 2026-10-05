"""``POST /api/v1/trends/ingest`` - automatizarea saptamanala trimite trendurile in trends_db.

Fara token de client sau de agentie: o apeleaza un job programat (GitHub Actions,
``scripts/trend_scraper.py``), cu ``CRON_SECRET_KEY`` in antetul ``X-Cron-Secret``. Fara
cheie configurata (sau una prea scurta), ruta e oprita - 503. La fiecare apel, intai se
sterge ce e mai vechi de 30 de zile, apoi trendurile primesc vectori si se salveaza
(``services/creative_memory.ingest_trends``).
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session

from ppc_agent_server.db import get_session
from ppc_agent_server.services.creative_context import TrendIngest, TrendIngestResult
from ppc_agent_server.services.creative_memory import ingest_trends
from ppc_agent_server.services.embeddings import Embedder, embedder_from_settings
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])

#: Sub atat, o cheie se poate ghici: ruta ramane oprita.
MIN_SECRET_CHARS = 32


def get_trend_embedder() -> Embedder:
    """Dependinta: modelul de embeddings de pe server (injectabil in teste)."""
    return embedder_from_settings(get_server_settings())


def require_cron_secret(x_cron_secret: Annotated[str | None, Header()] = None) -> None:
    """Antetul ``X-Cron-Secret`` trebuie sa fie exact ``CRON_SECRET_KEY``.

    Raises:
        HTTPException: 503 fara cheie configurata (sau prea scurta); 401 cheie gresita.
    """
    expected = get_server_settings().cron_secret_key
    if len(expected) < MIN_SECRET_CHARS:
        raise HTTPException(
            status_code=503,
            detail=f"ingestia de trenduri e oprită: CRON_SECRET_KEY lipsește sau are sub "
            f"{MIN_SECRET_CHARS} de caractere",
        )
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="cheie greșită")


@router.post(
    "/ingest",
    response_model=TrendIngestResult,
    dependencies=[Depends(require_cron_secret)],
)
def ingest(
    body: TrendIngest,
    session: Annotated[Session, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_trend_embedder)],
) -> TrendIngestResult:
    """Trendurile saptamanii: sterge ce e vechi (TTL 30 de zile), salveaza cu vectori."""
    return ingest_trends(session, body, embedder=embedder, today=datetime.now(tz=UTC).date())
