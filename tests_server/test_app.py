"""Teste pentru fabrica aplicatiei FastAPI si verificarea de viata."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect

from ppc_agent_server.app import MAX_BODY_BYTES, MAX_UPLOAD_BODY_BYTES, __version__


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


def test_a_declared_oversized_body_is_refused_before_it_is_read(client: TestClient) -> None:
    response = client.post(
        "/api/v1/login",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(MAX_BODY_BYTES + 1)},
    )
    assert response.status_code == 413
    assert "2 MB" in response.json()["detail"]


def test_a_chunked_body_is_cut_off_at_the_limit(client: TestClient) -> None:
    """Fara Content-Length (chunked), corpul e numarat pe masura ce soseste."""
    chunks = (b"x" * 1024 * 1024 for _ in range(3))
    response = client.post(
        "/api/v1/login", content=chunks, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_the_creative_upload_has_its_own_larger_limit(client: TestClient) -> None:
    """Un video de 50 MB trece de plafonul general; peste 60 MB, nici uploadul."""
    big = client.post(
        "/api/v1/creative/upload",
        content=b"",
        headers={"Content-Length": str(MAX_UPLOAD_BODY_BYTES + 1)},
    )
    assert big.status_code == 413
    within = client.post(
        "/api/v1/creative/upload",
        content=b"",
        headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
    )
    assert within.status_code != 413


def test_a_413_carries_cors_headers_so_the_site_can_show_it(client: TestClient) -> None:
    from ppc_agent_server.settings import get_server_settings

    origin = get_server_settings().cors_origins[0]
    response = client.post(
        "/api/v1/login",
        content=b"{}",
        headers={
            "Origin": origin,
            "Content-Type": "application/json",
            "Content-Length": str(MAX_BODY_BYTES + 1),
        },
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == origin
