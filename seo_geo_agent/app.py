"""Fabrica aplicatiei FastAPI pentru seo_geo_agent.

Ruleaza cu ``uvicorn seo_geo_agent.app:app --reload --port 8001`` (port diferit
de ``ppc_agent_server``, ca ambele sa poata rula simultan in dezvoltare - vezi
README.md).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from seo_geo_agent import __version__
from seo_geo_agent.errors import AnalysisError, SeoGeoAgentError, SetupRequiredError
from seo_geo_agent.router import router
from seo_geo_agent.settings import get_seo_geo_settings

# Mapare eroare -> cod HTTP, de la cea mai specifica la cea mai generala (vezi
# ppc_agent_server/app.py - acelasi motiv: Starlette parcurge __mro__-ul
# exceptiei si foloseste primul handler potrivit).
_ERROR_STATUS_CODES: dict[type[SeoGeoAgentError], int] = {
    SetupRequiredError: 503,
    AnalysisError: 502,  # LLM-ul a raspuns, dar cu ceva ce nu putem folosi - dependinta externa
    SeoGeoAgentError: 500,  # fallback generic - ramane ultimul inregistrat
}


def _error_handler(
    status_code: int,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def create_app() -> FastAPI:
    """Construieste instanta FastAPI (functie, nu obiect global - testabila izolat)."""
    app = FastAPI(
        title="seo-geo-agent",
        description=(
            "Agent AI separat: analiza SEO+GEO a unui domeniu, pe baza rapoartelor "
            "clientului. Nu face parte din ppc_agent_server (vezi __init__.py)."
        ),
        version=__version__,
    )

    for error_type, status_code in _ERROR_STATUS_CODES.items():
        app.add_exception_handler(error_type, _error_handler(status_code))

    # Site-ul de marketing (site/) cheama acest API direct din browser (fetch) -
    # fara CORS, cererea ar fi blocata inainte sa ajunga aici. Vezi
    # SeoGeoSettings.cors_origins pentru configurare.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_seo_geo_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Verificare de viata - nu atinge Ollama."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
