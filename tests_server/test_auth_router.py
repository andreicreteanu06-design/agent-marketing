"""Teste pentru POST /api/v1/auth/mcc-connect (stub — ridica SetupRequiredError)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_mcc_connect_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/mcc-connect",
        json={"platform": "google_ads", "authorization_code": "cod-oauth-fals"},
    )
    assert response.status_code == 401


def test_mcc_connect_returns_503_setup_required(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Exercita end-to-end handler-ul SetupRequiredError -> 503 al app.py."""
    response = client.post(
        "/api/v1/auth/mcc-connect",
        headers=auth_headers,
        json={"platform": "tiktok_ads", "authorization_code": "cod-oauth-fals"},
    )
    assert response.status_code == 503
    assert "tiktok_ads" in response.json()["detail"]


def test_mcc_connect_rejects_unknown_platform(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/auth/mcc-connect",
        headers=auth_headers,
        json={"platform": "bing_ads", "authorization_code": "x"},
    )
    assert response.status_code == 422  # validare Pydantic, nu ajunge in handler
