"""Teste end-to-end pentru POST /api/v1/tracking/conversion/{client_id}."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_client(client: TestClient, auth_headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/clients",
        headers=auth_headers,
        json={"name": "Client Test"},
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def test_ingest_gomag_purchase(client: TestClient, auth_headers: dict[str, str]) -> None:
    client_id = _create_client(client, auth_headers)
    payload = {
        "id": 1001,
        "total": "150.00",
        "currency": "RON",
        "billing": {"email": "client@exemplu.ro", "phone": "0712345678"},
    }
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=gomag",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["qualified"] is True
    assert body["event_id"] == "gomag_order_1001"
    assert body["deduplicated"] is False


def test_ingest_short_call_is_unqualified(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    payload = {"call_id": "c1", "caller_id": "0723456789", "duration_seconds": 20}
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=call_tracker",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["qualified"] is False
    assert "60s" in body["reason"]


def test_ingest_long_call_is_qualified(client: TestClient, auth_headers: dict[str, str]) -> None:
    client_id = _create_client(client, auth_headers)
    payload = {"call_id": "c2", "caller_id": "0723456789", "duration_seconds": 120}
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=call_tracker",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 201
    assert response.json()["qualified"] is True


def test_ingest_custom_web_payload(client: TestClient, auth_headers: dict[str, str]) -> None:
    client_id = _create_client(client, auth_headers)
    payload = {
        "event_id": "custom-1",
        "event_type": "lead",
        "client_id": "ignored-should-be-overridden",
        "source_platform": "custom_web",
    }
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=custom_web",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 201
    assert response.json()["qualified"] is True


def test_ingest_deduplicates_repeated_event(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    payload = {"id": 55, "total": "80.00", "currency": "RON"}
    url = f"/api/v1/tracking/conversion/{client_id}?source_platform=gomag"

    first = client.post(url, headers=auth_headers, json=payload)
    second = client.post(url, headers=auth_headers, json=payload)

    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True


def test_ingest_unknown_source_platform_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=shopify",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422


def test_ingest_malformed_gomag_payload_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform=gomag",
        headers=auth_headers,
        json={"no_id_or_number": True},
    )
    assert response.status_code == 422


def test_ingest_unowned_client_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/tracking/conversion/999999?source_platform=gomag",
        headers=auth_headers,
        json={"id": 1, "total": "10.00"},
    )
    assert response.status_code == 404


def test_ingest_without_auth_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tracking/conversion/1?source_platform=gomag",
        json={"id": 1, "total": "10.00"},
    )
    assert response.status_code == 401
