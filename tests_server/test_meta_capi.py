"""Meta Conversions API: forma evenimentului, trimiterea, si legatura cu webhook-ul.

Fara retea: ``httpx.MockTransport`` pentru ``send_event``, iar la nivel de ruta
``send_event`` e inlocuit cu un dublu care retine ce ar fi plecat.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from ppc_agent.errors import ProviderError
from ppc_agent_server.models import ConversionEvent, ConversionEventType
from ppc_agent_server.tracking import meta_capi
from ppc_agent_server.tracking.meta_capi import build_event, send_event
from ppc_agent_server.tracking.models import StandardizedConversion, hash_pii

_PIXEL = "123456789012345"


def _event(**overrides: Any) -> ConversionEvent:
    fields: dict[str, Any] = {
        "client_account_id": 1,
        "event_id": "gomag_order_1001",
        "event_type": ConversionEventType.PURCHASE,
        "value": Decimal("150.00"),
        "currency": "RON",
        "email_sha256": hash_pii("client@exemplu.ro"),
        "phone_sha256": hash_pii("0712345678", is_phone=True),
        "source_platform": "gomag",
        "qualified": True,
        "created_at": datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return ConversionEvent(**fields)


def _conversion(**overrides: Any) -> StandardizedConversion:
    fields: dict[str, Any] = {
        "event_id": "gomag_order_1001",
        "client_id": "1",
        "source_platform": "gomag",
    }
    fields.update(overrides)
    return StandardizedConversion(**fields)


# --- forma evenimentului ------------------------------------------------------


def test_o_comanda_pleaca_cu_event_id_ul_nostru_si_pii_hash_uit() -> None:
    payload = build_event(_event(), _conversion())

    assert payload["event_name"] == "Purchase"
    assert payload["event_id"] == "gomag_order_1001"  # cheia de deduplicare cu pixelul
    assert payload["event_time"] == int(datetime(2026, 9, 30, 12, 0, tzinfo=UTC).timestamp())
    assert payload["custom_data"] == {"value": 150.0, "currency": "RON"}
    assert payload["user_data"]["em"] == [hashlib.sha256(b"client@exemplu.ro").hexdigest()]
    assert payload["user_data"]["ph"] == [hashlib.sha256(b"40712345678").hexdigest()]
    # Fara user-agent, Meta nu accepta "website": comanda raportata de server.
    assert payload["action_source"] == "other"
    assert "client@exemplu.ro" not in json.dumps(payload)


def test_cu_semnale_de_browser_devine_eveniment_de_website() -> None:
    payload = build_event(
        _event(),
        _conversion(
            event_time=1_790_000_000,
            event_source_url="https://exemplu.ro/multumim",
            client_user_agent="Mozilla/5.0",
            client_ip_address="203.0.113.7",
            fbp="fb.1.1700000000.123",
            fbc="fb.1.1700000000.AbCd",
        ),
    )
    assert payload["action_source"] == "website"
    assert payload["event_time"] == 1_790_000_000
    assert payload["event_source_url"] == "https://exemplu.ro/multumim"
    assert payload["user_data"]["client_user_agent"] == "Mozilla/5.0"
    assert payload["user_data"]["fbp"] == "fb.1.1700000000.123"


def test_un_apel_e_contact_prin_telefon() -> None:
    payload = build_event(
        _event(event_type=ConversionEventType.PHONE_CALL, value=None, email_sha256=None),
        _conversion(),
    )
    assert payload["event_name"] == "Contact"
    assert payload["action_source"] == "phone_call"
    assert "custom_data" not in payload
    assert "em" not in payload["user_data"]


# --- trimiterea ---------------------------------------------------------------


def _transport(response: httpx.Response, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return httpx.MockTransport(handler)


def test_trimiterea_bate_in_pixel_cu_token_si_codul_de_test() -> None:
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json={"events_received": 1, "fbtrace_id": "x"})

    send_event(
        {"event_id": "e1"},
        pixel_id=_PIXEL,
        access_token="tok",
        test_event_code="TEST123",
        transport=_transport(ok, seen),
    )

    [request] = seen
    assert request.url.path.endswith(f"/{_PIXEL}/events")
    assert request.headers["authorization"] == "Bearer tok"
    form = dict(httpx.QueryParams(request.content.decode()))
    assert json.loads(form["data"]) == [{"event_id": "e1"}]
    assert form["test_event_code"] == "TEST123"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": {"message": "Invalid parameter"}}),
        httpx.Response(200, json={"events_received": 0}),
        httpx.Response(200, json={"error": {"message": "eroare in corp"}}),
        httpx.Response(502, text="<html>bad gateway</html>"),
    ],
)
def test_orice_lipsa_de_confirmare_e_un_esec(response: httpx.Response) -> None:
    with pytest.raises(ProviderError):
        send_event({}, pixel_id=_PIXEL, access_token="tok", transport=_transport(response, []))


def test_un_pixel_care_nu_e_numeric_nu_ajunge_in_url() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ProviderError, match="pixel"):
        send_event(
            {},
            pixel_id="../me",
            access_token="tok",
            transport=_transport(httpx.Response(200), seen),
        )
    assert seen == []


# --- prin webhook ---------------------------------------------------------------


class _CapiStub:
    """``send_event`` inlocuit: retine ce ar fi plecat, pica la comanda."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_next = False

    def __call__(self, payload: dict[str, Any], **kwargs: Any) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ProviderError("Meta CAPI a refuzat (HTTP 500): temporar")
        self.sent.append({"payload": payload, **kwargs})


@pytest.fixture
def capi(monkeypatch: pytest.MonkeyPatch) -> _CapiStub:
    stub = _CapiStub()
    monkeypatch.setattr(meta_capi, "send_event", stub)
    return stub


@pytest.fixture
def meta_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "token-de-test")


def _client_with_pixel(client: TestClient, headers: dict[str, str], name: str = "C") -> int:
    response = client.post(
        "/api/v1/clients", headers=headers, json={"name": name, "meta_pixel_id": _PIXEL}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _post(client: TestClient, headers: dict[str, str], client_id: int, payload: dict[str, Any],
          source: str = "gomag") -> dict[str, Any]:
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform={source}",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


_ORDER = {"id": 1001, "total": "150.00", "currency": "RON", "billing": {"email": "a@b.ro"}}


def test_o_comanda_calificata_pleaca_o_singura_data(
    client: TestClient, auth_headers: dict[str, str], meta_live: None, capi: _CapiStub
) -> None:
    client_id = _client_with_pixel(client, auth_headers)

    first = _post(client, auth_headers, client_id, _ORDER)
    again = _post(client, auth_headers, client_id, _ORDER)  # webhook retrimis

    assert first["meta_capi"] == "sent"
    assert again["deduplicated"] is True
    assert again["meta_capi"] is None
    [call] = capi.sent
    assert call["pixel_id"] == _PIXEL
    assert call["access_token"] == "token-de-test"
    assert call["payload"]["event_id"] == "gomag_order_1001"


def test_un_esec_meta_nu_pierde_conversia_si_se_reincearca_la_retrimitere(
    client: TestClient, auth_headers: dict[str, str], meta_live: None, capi: _CapiStub
) -> None:
    client_id = _client_with_pixel(client, auth_headers)
    capi.fail_next = True

    first = _post(client, auth_headers, client_id, _ORDER)
    retry = _post(client, auth_headers, client_id, _ORDER)

    assert first["qualified"] is True
    assert first["meta_capi"] == "failed"
    assert retry["deduplicated"] is True
    assert retry["meta_capi"] == "sent"
    assert len(capi.sent) == 1


def test_un_apel_scurt_necalificat_nu_ajunge_la_meta(
    client: TestClient, auth_headers: dict[str, str], meta_live: None, capi: _CapiStub
) -> None:
    client_id = _client_with_pixel(client, auth_headers)
    body = _post(
        client,
        auth_headers,
        client_id,
        {"call_id": "c1", "caller_id": "0723456789", "duration_seconds": 20},
        source="call_tracker",
    )
    assert body["qualified"] is False
    assert body["meta_capi"] is None
    assert capi.sent == []


def test_in_mod_mock_nu_pleaca_nimic(
    client: TestClient, auth_headers: dict[str, str], capi: _CapiStub
) -> None:
    client_id = _client_with_pixel(client, auth_headers)
    assert _post(client, auth_headers, client_id, _ORDER)["meta_capi"] is None
    assert capi.sent == []


def test_fara_token_esecul_e_vizibil(
    client: TestClient,
    auth_headers: dict[str, str],
    capi: _CapiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "")
    client_id = _client_with_pixel(client, auth_headers)
    assert _post(client, auth_headers, client_id, _ORDER)["meta_capi"] == "failed"
    assert capi.sent == []


def test_aceeasi_comanda_la_doi_clienti_nu_se_deduplica_intre_ei(
    client: TestClient, auth_headers: dict[str, str], meta_live: None, capi: _CapiStub
) -> None:
    """Comanda Gomag #1001 a unui magazin nu e comanda #1001 a altuia."""
    first_client = _client_with_pixel(client, auth_headers, "Magazin A")
    second_client = _client_with_pixel(client, auth_headers, "Magazin B")

    first = _post(client, auth_headers, first_client, _ORDER)
    second = _post(client, auth_headers, second_client, _ORDER)

    assert first["deduplicated"] is False
    assert second["deduplicated"] is False
    assert second["meta_capi"] == "sent"
    assert len(capi.sent) == 2


def test_un_pixel_invalid_e_refuzat_la_configurare(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/clients", headers=auth_headers, json={"name": "X", "meta_pixel_id": "../me"}
    )
    assert response.status_code == 422
