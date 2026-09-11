"""Fabrica aplicatiei FastAPI.

Ruleaza cu ``uvicorn ppc_agent_server.app:app --reload``. Fara rute de business
inca (Faza D e doar schela: DB + autentificare) — acelea vin in Faza E.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ppc_agent_server.db import init_db

__version__ = "0.1.0"


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

    @app.get("/health")
    def health() -> dict[str, str]:
        """Verificare de viata — nu atinge baza de date."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
