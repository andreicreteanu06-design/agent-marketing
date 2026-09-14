"""Teste deterministe pentru LiveGoogleAdsProvider, fara retea reala.

Foloseste ``httpx.MockTransport`` (acelasi pattern ca ``test_llm_live.py``
pentru ``LiveLLMClient``) - niciun apel de retea nu paraseste procesul de test.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider

_OAUTH_URL = "https://oauth2.googleapis.com/token"
_SEARCH_URL = "https://googleads.googleapis.com/v25/customers/123/googleAds:search"


def _provider(handler: httpx.MockTransport, **overrides: object) -> LiveGoogleAdsProvider:
    defaults: dict[str, object] = dict(
        developer_token="dev-token",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        transport=handler,
    )
    defaults.update(overrides)
    return LiveGoogleAdsProvider(**defaults)  # type: ignore[arg-type]


def _oauth_ok(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == _OAUTH_URL
    return httpx.Response(200, json={"access_token": "access-123", "expires_in": 3599})


def test_missing_credentials_raises_without_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveGoogleAdsProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("123")


def test_missing_customer_id_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        raise AssertionError("nu ar trebui sa ajunga la search fara customer_id")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("")


def test_campaign_performance_maps_rows_correctly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        assert str(request.url) == _SEARCH_URL
        assert request.headers["developer-token"] == "dev-token"
        assert request.headers["authorization"] == "Bearer access-123"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "campaign": {"id": "111", "name": "Search - Brand"},
                        "metrics": {
                            "clicks": "1200",
                            "conversions": 168.0,
                            "costMicros": "900000000",
                            "conversionsValue": 4200.0,
                        },
                    }
                ]
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    frame = provider.campaign_performance("123")
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["arm_id"] == "111"
    assert row["name"] == "Search - Brand"
    assert row["clicks"] == 1200
    assert row["conversions"] == 168
    assert row["cost"] == pytest.approx(900.0)
    assert row["revenue"] == pytest.approx(4200.0)


def test_pagination_follows_next_page_token() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        calls["count"] += 1
        body = json.loads(request.content)
        if "pageToken" not in body:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "campaign": {"id": "1", "name": "A"},
                            "metrics": {
                                "clicks": "10",
                                "conversions": 1,
                                "costMicros": "1000000",
                                "conversionsValue": 5,
                            },
                        }
                    ],
                    "nextPageToken": "page2",
                },
            )
        assert body["pageToken"] == "page2"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "campaign": {"id": "2", "name": "B"},
                        "metrics": {
                            "clicks": "20",
                            "conversions": 2,
                            "costMicros": "2000000",
                            "conversionsValue": 10,
                        },
                    }
                ]
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    frame = provider.campaign_performance("123")
    assert calls["count"] == 2
    assert set(frame["arm_id"]) == {"1", "2"}


def test_401_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        return httpx.Response(401, json={"error": {"message": "invalid token"}})

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("123")


def test_oauth_refresh_rejected_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("123")


def test_malformed_row_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        return httpx.Response(200, json={"results": [{"campaign": {"id": "1"}}]})

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        provider.campaign_performance("123")


def test_server_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        return httpx.Response(500, text="internal error")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        provider.campaign_performance("123")


def test_conversion_paths_single_touch_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "campaign": {"id": "1", "name": "A"},
                        "metrics": {
                            "clicks": "10",
                            "conversions": 3,
                            "costMicros": "1000000",
                            "conversionsValue": 5,
                        },
                    }
                ]
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    paths = provider.conversion_paths("123")
    assert len(paths) == 10
    assert sum(1 for p in paths if p[-1] == "conversion") == 3
    assert sum(1 for p in paths if p[-1] == "null") == 7
    assert all(p[0] == "A" for p in paths)


def test_conversion_paths_caps_high_click_volume() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return _oauth_ok(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "campaign": {"id": "1", "name": "A"},
                        "metrics": {
                            "clicks": "10000",
                            "conversions": 1000,
                            "costMicros": "1000000",
                            "conversionsValue": 5,
                        },
                    }
                ]
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    paths = provider.conversion_paths("123")
    assert len(paths) == 500
