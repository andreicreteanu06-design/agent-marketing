"""Fabrica aplicatiei FastAPI.

Ruleaza cu ``uvicorn ppc_agent_server.app:app --reload``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ppc_agent.errors import (
    ApprovalRequiredError,
    CopywriterError,
    PpcAgentError,
    ProviderError,
    SetupRequiredError,
    SpendLimitExceeded,
)
from ppc_agent_server.db import init_db
from ppc_agent_server.routers import (
    auth,
    campaigns,
    client_auth,
    clients,
    hybrid_insights,
    integrations,
    jobs,
    proposals,
    queen,
    reports,
    seo_intelligence,
    tracking,
)
from ppc_agent_server.routers.mcp_router import MCP_MOUNT_PATH, build_mcp_asgi_app
from ppc_agent_server.settings import get_server_settings

__version__ = "0.1.0"

# Mapare eroare -> cod HTTP. Inregistrate de la cea mai specifica la cea mai
# generala — Starlette parcurge __mro__-ul exceptiei si foloseste primul
# handler potrivit, deci subclasele nemetionate explicit (SwipeFileError,
# AdsLimitError, TikTokIngestError sub CopywriterError; orice ramane sub
# PpcAgentError) mostenesc automat tratamentul parintelui lor.
_ERROR_STATUS_CODES: dict[type[PpcAgentError], int] = {
    SetupRequiredError: 503,
    SpendLimitExceeded: 409,
    ApprovalRequiredError: 403,
    CopywriterError: 422,
    ProviderError: 502,  # API-ul live a raspuns, dar cu o eroare - dependinta externa
    PpcAgentError: 500,  # fallback generic — ramane ultimul inregistrat
}


def _error_handler(
    status_code: int,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    # Semnatura cere Exception (nu PpcAgentError), ca sa se potriveasca cu
    # tipul exact asteptat de Starlette.add_exception_handler — la runtime
    # e apelat doar cu instante ale tipului inregistrat (dispatch pe __mro__).
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """La pornire: creeaza tabelele lipsa (SQLite dev) — Postgres foloseste Alembic."""
    init_db()
    yield


def create_app() -> FastAPI:
    """Construieste instanta FastAPI (functie, nu obiect global — testabila izolat)."""
    app = FastAPI(
        title="ppc-agent server",
        description="Backend B2B multi-tenant pentru agentii, peste pipeline-urile ppc_agent.",
        version=__version__,
        lifespan=lifespan,
    )

    for error_type, status_code in _ERROR_STATUS_CODES.items():
        app.add_exception_handler(error_type, _error_handler(status_code))

    # Site-ul de marketing (site/) e servit separat (Next.js, alt port/domeniu)
    # si cheama acest API direct din browser (fetch) - fara CORS, orice cerere
    # de la /signup, /login etc. ar fi blocata de browser inainte sa ajunga
    # aici. Vezi ServerSettings.cors_allowed_origins pentru configurare.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_server_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(campaigns.router)
    app.include_router(client_auth.router)
    app.include_router(clients.router)
    app.include_router(hybrid_insights.router)
    app.include_router(integrations.router)
    app.include_router(jobs.router)
    app.include_router(proposals.router)
    app.include_router(queen.router)
    app.include_router(reports.router)
    app.include_router(seo_intelligence.router)
    app.include_router(tracking.router)

    # Serverul MCP e o aplicatie ASGI separata, montata - nu un APIRouter:
    # SSE-ul isi tine propriul ciclu de viata al conexiunii, iar schema lui de
    # unelte nu apartine OpenAPI-ului REST.
    app.mount(MCP_MOUNT_PATH, build_mcp_asgi_app())

    @app.get("/health")
    def health() -> dict[str, str]:
        """Verificare de viata — nu atinge baza de date."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
