"""Teste pentru ``POST /api/v1/clients``."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_client_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/clients", json={"name": "Client fara auth"})
    assert response.status_code == 401


def test_create_client_persists_and_returns_it(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/clients",
        headers=auth_headers,
        json={
            "name": "FacturarePro SRL",
            "target_domain": "https://facturarepro.ro",
            "max_daily_spend": "75.00",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "FacturarePro SRL"
    assert body["target_domain"] == "https://facturarepro.ro"
    assert body["max_daily_spend"] == "75.00"
    assert body["geo"] == "RO"  # implicit
    assert "id" in body and "created_at" in body


def test_create_client_uses_defaults_when_omitted(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/clients", headers=auth_headers, json={"name": "Client minimal"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["max_daily_spend"] == "50.00"
    assert body["language"] == "ro"


def test_invalid_api_key_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/clients",
        headers={"Authorization": "Bearer pk_nu_exista"},
        json={"name": "x"},
    )
    assert response.status_code == 401
