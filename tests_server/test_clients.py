"""Teste pentru ``/api/v1/clients`` - creare, listare, citire, actualizare."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_client(
    client: TestClient, auth_headers: dict[str, str], **overrides: object
) -> int:
    payload: dict[str, object] = {"name": "Client Test"}
    payload.update(overrides)
    response = client.post("/api/v1/clients", headers=auth_headers, json=payload)
    assert response.status_code == 201
    return int(response.json()["id"])


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
            "default_lead_value": "150.00",
            "objective": "sales",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "FacturarePro SRL"
    assert body["target_domain"] == "https://facturarepro.ro"
    assert body["max_daily_spend"] == "75.00"
    assert body["default_lead_value"] == "150.00"
    assert body["objective"] == "sales"
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
    assert body["default_lead_value"] == "300.00"
    assert body["objective"] == "lead_generation"
    assert body["language"] == "ro"


def test_invalid_api_key_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/clients",
        headers={"Authorization": "Bearer pk_nu_exista"},
        json={"name": "x"},
    )
    assert response.status_code == 401


def test_list_clients_returns_only_tenants_own(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _create_client(client, auth_headers, name="Client A")
    _create_client(client, auth_headers, name="Client B")

    response = client.get("/api/v1/clients", headers=auth_headers)
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert names == {"Client A", "Client B"}


def test_list_clients_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/clients").status_code == 401


def test_get_single_client(client: TestClient, auth_headers: dict[str, str]) -> None:
    client_id = _create_client(client, auth_headers, name="Client Unic")
    response = client.get(f"/api/v1/clients/{client_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Client Unic"


def test_get_client_not_owned_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/clients/999999", headers=auth_headers)
    assert response.status_code == 404


def test_update_client_default_lead_value(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Motivul principal al PATCH: corectarea default_lead_value dupa ce agentia
    afla rata reala de inchidere a vanzarilor - vezi ClientAccountUpdate."""
    client_id = _create_client(client, auth_headers, default_lead_value="300.00")

    response = client.patch(
        f"/api/v1/clients/{client_id}",
        headers=auth_headers,
        json={"default_lead_value": "180.00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["default_lead_value"] == "180.00"


def test_update_client_only_changes_sent_fields(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(
        client, auth_headers, name="Nume Original", max_daily_spend="40.00"
    )

    response = client.patch(
        f"/api/v1/clients/{client_id}", headers=auth_headers, json={"name": "Nume Nou"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Nume Nou"
    assert body["max_daily_spend"] == "40.00"  # neschimbat


def test_update_client_rejects_non_positive_lead_value(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    response = client.patch(
        f"/api/v1/clients/{client_id}",
        headers=auth_headers,
        json={"default_lead_value": "0"},
    )
    assert response.status_code == 422


def test_update_client_not_owned_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.patch(
        "/api/v1/clients/999999", headers=auth_headers, json={"name": "x"}
    )
    assert response.status_code == 404


def test_update_client_break_even_roas_and_back_to_the_default(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Magazin cu marja de 40%: ROAS minim 2,5. ``null`` revine la implicitul obiectivului."""
    client_id = _create_client(client, auth_headers)
    url = f"/api/v1/clients/{client_id}"

    set_margin = client.patch(url, headers=auth_headers, json={"min_roas": "2.5"})
    assert set_margin.status_code == 200
    assert set_margin.json()["min_roas"] == "2.50"
    cleared = client.patch(url, headers=auth_headers, json={"min_roas": None})
    assert cleared.json()["min_roas"] is None
    assert client.patch(url, headers=auth_headers, json={"min_roas": "0"}).status_code == 422
