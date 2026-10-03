"""Conversiile spre Google Ads, TikTok si ChatGPT: forma fiecarui eveniment si drumul lor.

Fara retea: cererile catre platforme sunt inlocuite. Se verifica ce pleaca (id-urile
de click, hash-urile in forma ceruta de fiecare platforma) si cand nu pleaca nimic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.errors import ProviderError
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider
from ppc_agent_server.models import ClientAccount, ConversionEventType, Tenant
from ppc_agent_server.security import encrypt_secret
from ppc_agent_server.tracking import platform_conversions
from ppc_agent_server.tracking.models import hash_email_google, hash_phone_e164
from ppc_agent_server.tracking.platform_conversions import (
    build_chatgpt_event,
    build_google_conversion,
    build_tiktok_event,
    send_chatgpt_events,
)
from tests_server.test_meta_capi import _conversion, _event


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- hash-urile fiecarei platforme ----------------------------------------------------


def test_google_drops_the_dots_of_a_gmail_address_before_hashing() -> None:
    assert hash_email_google(" Jane.Doe@Gmail.com ") == _sha("janedoe@gmail.com")
    # Doar la Gmail: la alte domenii punctul face parte din adresa.
    assert hash_email_google("jane.doe@firma.ro") == _sha("jane.doe@firma.ro")


def test_google_and_tiktok_want_the_phone_with_a_plus() -> None:
    assert hash_phone_e164("0712 345 678") == _sha("+40712345678")
    assert hash_phone_e164("0040712345678") == _sha("+40712345678")


# --- Google Ads ---------------------------------------------------------------------


def test_a_google_conversion_carries_the_click_value_and_hashed_contact() -> None:
    payload = build_google_conversion(
        _event(),
        _conversion(
            gclid="Cj0KCQ",
            customer_email="jane.doe@gmail.com",
            customer_phone="0712345678",
            marketing_consent=True,
        ),
        customer_id="1234567890",
        conversion_action_id="987",
    )

    assert payload == {
        "conversionAction": "customers/1234567890/conversionActions/987",
        "conversionDateTime": "2026-09-30 12:00:00+00:00",
        "orderId": "gomag_order_1001",
        "gclid": "Cj0KCQ",
        "userIdentifiers": [
            {"hashedEmail": _sha("janedoe@gmail.com")},
            {"hashedPhoneNumber": _sha("+40712345678")},
        ],
        "conversionValue": 150.0,
        "currencyCode": "RON",
        "consent": {"adUserData": "GRANTED"},
    }


def test_an_ios_click_uses_gbraid_and_nothing_to_match_means_nothing_sent() -> None:
    ios = build_google_conversion(
        _event(), _conversion(gbraid="0AAAA"), customer_id="1", conversion_action_id="2"
    )
    assert ios is not None and ios["gbraid"] == "0AAAA" and "gclid" not in ios

    assert (
        build_google_conversion(_event(), _conversion(), customer_id="1", conversion_action_id="2")
        is None
    )


# --- TikTok -------------------------------------------------------------------------


def test_a_tiktok_event_carries_ttclid_ttp_and_hashed_contact() -> None:
    payload = build_tiktok_event(
        _event(),
        _conversion(
            ttclid="E.C.P.abc",
            ttp="cookie-ttp",
            customer_email="Client@Exemplu.ro",
            customer_phone="0712345678",
            event_source_url="https://magazin.ro/multumim",
        ),
        pixel_code="C4PIXEL",
        test_event_code="TEST123",
    )

    assert payload["event_source"] == "web"
    assert payload["event_source_id"] == "C4PIXEL"
    assert payload["test_event_code"] == "TEST123"
    [data] = payload["data"]
    assert data["event"] == "CompletePayment"
    assert data["event_id"] == "gomag_order_1001"
    assert data["user"] == {
        "ttclid": "E.C.P.abc",
        "ttp": "cookie-ttp",
        "email": _sha("client@exemplu.ro"),
        "phone": _sha("+40712345678"),
    }
    assert data["properties"] == {"value": 150.0, "currency": "RON"}
    assert data["page"] == {"url": "https://magazin.ro/multumim"}


# --- ChatGPT (OpenAI Ads) -----------------------------------------------------------


def test_a_chatgpt_order_is_sent_in_minor_units_with_the_oppref() -> None:
    event = _event()
    payload = build_chatgpt_event(
        event, _conversion(oppref="opp_123"), fallback_url="https://magazin.ro"
    )

    assert payload is not None
    assert payload["type"] == "order_created"
    assert payload["id"] == "gomag_order_1001"
    assert payload["oppref"] == "opp_123"
    assert payload["source_url"] == "https://magazin.ro"
    assert payload["data"] == {"type": "contents", "amount": 15000, "currency": "RON"}
    assert payload["user"]["emails_sha256"] == [event.email_sha256]


def test_chatgpt_has_no_event_for_a_phone_call() -> None:
    call = _event(event_type=ConversionEventType.PHONE_CALL)
    assert build_chatgpt_event(call, _conversion(), fallback_url="https://x.ro") is None


def test_the_chatgpt_events_api_gets_the_pixel_and_the_partner_source() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    send_chatgpt_events(
        [{"id": "1"}], pixel_id="px_1", api_key="key", transport=httpx.MockTransport(handler)
    )

    [request] = seen
    assert request.url.params["pid"] == "px_1"
    assert request.headers["authorization"] == "Bearer key"
    body = json.loads(request.content)
    assert body == {
        "validate_only": False,
        "integration_source": "ac_media",
        "events": [{"id": "1"}],
    }

    refused = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": {"message": "invalid oppref"}})
    )
    with pytest.raises(ProviderError, match="invalid oppref"):
        send_chatgpt_events([{"id": "1"}], pixel_id="px_1", api_key="key", transport=refused)


# --- drumul prin webhook ------------------------------------------------------------


class _Platforms:
    """Cererile spre Google, TikTok si OpenAI, inlocuite: retin ce ar fi plecat.

    Metodele sunt deja legate de stub: puse pe clasa providerului, primesc doar
    argumentele apelului, fara providerul insusi.
    """

    def __init__(self) -> None:
        self.google: list[dict[str, Any]] = []
        self.tiktok: list[dict[str, Any]] = []
        self.chatgpt: list[dict[str, Any]] = []
        self.fail_google = False

    def upload(self, customer_id: str, conversion: dict[str, Any]) -> None:
        if self.fail_google:
            self.fail_google = False
            raise ProviderError("Google Ads a refuzat conversia: click negasit")
        self.google.append({"customer_id": customer_id, **conversion})

    def track(self, payload: dict[str, Any]) -> None:
        self.tiktok.append(payload)

    def openai(self, events: list[dict[str, Any]], **kwargs: Any) -> None:
        self.chatgpt.extend(events)


@pytest.fixture
def platforms(monkeypatch: pytest.MonkeyPatch, agency_settings: Tenant) -> _Platforms:
    stub = _Platforms()
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_GOOGLE_ADS_DEVELOPER_TOKEN", "dev")
    monkeypatch.setenv("PPC_GOOGLE_ADS_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("PPC_TIKTOK_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("PPC_TIKTOK_ADVERTISER_ID", "adv")
    monkeypatch.setattr(LiveGoogleAdsProvider, "upload_click_conversion", stub.upload)
    monkeypatch.setattr(LiveTikTokAdsProvider, "track_event", stub.track)
    monkeypatch.setattr(platform_conversions, "send_chatgpt_events", stub.openai)
    return stub


def _connected_client(client: TestClient, headers: dict[str, str], session: Session) -> int:
    response = client.post(
        "/api/v1/clients",
        headers=headers,
        json={
            "name": "Magazin",
            "objective": "sales",
            "google_ads_customer_id": "123-456-7890",
            "google_ads_conversion_action_id": "987",
            "tiktok_pixel_code": "C4PIXEL",
            "chatgpt_pixel_id": "px_1",
        },
    )
    assert response.status_code == 201, response.text
    client_id = int(response.json()["id"])
    account = session.get(ClientAccount, client_id)
    assert account is not None
    account.chatgpt_conversions_key_enc = encrypt_secret("cheie-conversii")
    session.add(account)
    session.commit()
    return client_id


_ORDER = {
    "id": 2002,
    "total": "150.00",
    "billing": {"email": "a@b.ro"},
    "gclid": "Cj0KCQ",
    "ttclid": "E.C.P.abc",
    "oppref": "opp_123",
}


def _post(
    client: TestClient,
    headers: dict[str, str],
    client_id: int,
    payload: dict[str, Any],
    source: str = "gomag",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/tracking/conversion/{client_id}?source_platform={source}",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_an_order_reaches_google_tiktok_and_chatgpt_once(
    client: TestClient, auth_headers: dict[str, str], session: Session, platforms: _Platforms
) -> None:
    client_id = _connected_client(client, auth_headers, session)

    first = _post(client, auth_headers, client_id, _ORDER)
    again = _post(client, auth_headers, client_id, _ORDER)  # webhook retrimis

    assert (first["google_ads"], first["tiktok"], first["chatgpt"]) == ("sent", "sent", "sent")
    assert (again["google_ads"], again["tiktok"], again["chatgpt"]) == (None, None, None)
    [google] = platforms.google
    assert google["customer_id"] == "1234567890"
    assert google["gclid"] == "Cj0KCQ"
    [tiktok] = platforms.tiktok
    assert tiktok["data"][0]["user"]["ttclid"] == "E.C.P.abc"
    [chatgpt] = platforms.chatgpt
    assert chatgpt["oppref"] == "opp_123"


def test_a_refused_conversion_is_retried_when_the_webhook_comes_again(
    client: TestClient, auth_headers: dict[str, str], session: Session, platforms: _Platforms
) -> None:
    client_id = _connected_client(client, auth_headers, session)
    platforms.fail_google = True

    first = _post(client, auth_headers, client_id, _ORDER)
    retry = _post(client, auth_headers, client_id, _ORDER)

    assert first["google_ads"] == "failed"
    assert first["tiktok"] == "sent"
    assert retry["google_ads"] == "sent"
    assert retry["tiktok"] is None
    assert len(platforms.google) == len(platforms.tiktok) == 1


def test_a_customer_who_refused_marketing_cookies_is_not_sent_anywhere(
    client: TestClient, auth_headers: dict[str, str], session: Session, platforms: _Platforms
) -> None:
    client_id = _connected_client(client, auth_headers, session)

    body = _post(
        client,
        auth_headers,
        client_id,
        {
            "event_id": "web_1",
            "source_platform": "custom_web",
            "value": 150,
            "gclid": "Cj0KCQ",
            "ttclid": "E.C.P.abc",
            "marketing_consent": False,
        },
        source="custom_web",
    )

    assert body["qualified"] is True
    assert (body["google_ads"], body["tiktok"], body["chatgpt"], body["meta_capi"]) == (
        None,
        None,
        None,
        None,
    )
    assert platforms.google == platforms.tiktok == platforms.chatgpt == []
