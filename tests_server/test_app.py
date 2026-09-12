"""Teste pentru fabrica aplicatiei FastAPI si verificarea de viata."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect

from ppc_agent_server.app import __version__


def test_health_check_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_lifespan_creates_tables(client: TestClient, engine: Engine) -> None:
    """Pornirea aplicatiei (lifespan) creeaza tabelele lipsa — fara migratie manuala."""
    tables = set(inspect(engine).get_table_names())
    expected = {
        "tenant",
        "clientaccount",
        "proposedchange",
        "adqueueitem",
        "creativeartifact",
        "conversionevent",
        "adperformancerecord",
    }
    assert expected <= tables
