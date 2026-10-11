"""Cheia de webhook per client: merge doar pe webhook-ul clientului ei."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.auth import create_tenant
from ppc_agent_server.models import Tenant
from ppc_agent_server.security import verify_webhook_key, webhook_key
from ppc_agent_server.settings import get_server_settings

_ORDER = {"id": 7, "total": "99.00", "currency": "RON", "billing": {"email": "a@b.ro"}}


def _create_client(client: TestClient, headers: dict[str, str], name: str) -> int:
    response = client.post("/api/v1/clients", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _key(client: TestClient, headers: dict[str, str], client_id: int) -> str:
    response = client.get(f"/api/v1/clients/{client_id}/webhook-key", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["webhook_path"] == f"/api/v1/tracking/conversion/{client_id}"
    return str(body["key"])


def _webhook(
    client: TestClient,
    client_id: int,
    *,
    headers: dict[str, str] | None = None,
    key: str | None = None,
) -> int:
    params = {"source_platform": "gomag", **({"key": key} if key else {})}
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}", json=_ORDER, params=params, headers=headers
    )
    return response.status_code


def test_cheia_e_derivata_stabila_si_diferita_pe_client(agency_settings: Tenant) -> None:
    first, second = webhook_key(1), webhook_key(2)
    assert first.startswith("whk_") and first == webhook_key(1)
    assert first != second
    assert verify_webhook_key(first, 1) and not verify_webhook_key(first, 2)


def test_fara_secret_pe_server_cheia_nu_se_poate_deriva(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    get_server_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            webhook_key(1)
    finally:
        get_server_settings.cache_clear()


def test_cheia_clientului_merge_in_antet_si_in_url(
    client: TestClient, auth_headers: dict[str, str], agency_settings: Tenant
) -> None:
    client_id = _create_client(client, auth_headers, "Magazin")
    key = _key(client, auth_headers, client_id)

    assert _webhook(client, client_id, headers={"Authorization": f"Bearer {key}"}) == 201
    assert _webhook(client, client_id, key=key) == 201  # Gomag: doar un URL


def test_cheia_unui_client_nu_deschide_alt_client(
    client: TestClient, auth_headers: dict[str, str], agency_settings: Tenant
) -> None:
    first = _create_client(client, auth_headers, "Primul")
    second = _create_client(client, auth_headers, "Al doilea")
    key = _key(client, auth_headers, first)

    assert _webhook(client, second, key=key) == 401
    assert _webhook(client, second, headers={"Authorization": f"Bearer {key}"}) == 401


def test_o_cheie_falsa_e_refuzata(
    client: TestClient, auth_headers: dict[str, str], agency_settings: Tenant
) -> None:
    client_id = _create_client(client, auth_headers, "Magazin")
    assert _webhook(client, client_id, key="whk_inventata") == 401
    assert _webhook(client, client_id, key="pk_cheia_agentiei_in_url") == 401
    assert _webhook(client, client_id) == 401  # nicio cheie


def test_cheia_agentiei_merge_in_continuare(
    client: TestClient, auth_headers: dict[str, str], agency_settings: Tenant
) -> None:
    client_id = _create_client(client, auth_headers, "Magazin")
    assert _webhook(client, client_id, headers=auth_headers) == 201


def test_alta_agentie_nu_poate_lua_cheia_clientului(
    client: TestClient, auth_headers: dict[str, str], agency_settings: Tenant, session: Session
) -> None:
    client_id = _create_client(client, auth_headers, "Magazin")
    _, other_key = create_tenant(session, "Alta agentie")
    response = client.get(
        f"/api/v1/clients/{client_id}/webhook-key",
        headers={"Authorization": f"Bearer {other_key}"},
    )
    assert response.status_code == 404
