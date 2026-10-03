"""Teste deterministe pentru LiveTikTokAdsProvider, fara retea reala.

Foloseste ``httpx.MockTransport`` (acelasi pattern ca ``test_llm_live.py``).
"""

from __future__ import annotations

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider

_REPORT_URL = "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/"


def test_missing_access_token_raises_without_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveTikTokAdsProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("adv_1")


def test_missing_advertiser_id_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP fara advertiser_id")

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("")


_ADGROUP_URL = "https://business-api.tiktok.com/open_api/v1.3/adgroup/get/"


def _ok(rows: list[dict[str, object]], *, total_page: int = 1, page: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "OK",
            "data": {"list": rows, "page_info": {"page": page, "total_page": total_page}},
        },
    )


_ROW = {
    "dimensions": {"adgroup_id": "tt_1"},
    "metrics": {
        "adgroup_name": "Spark Ads",
        "clicks": "3200",
        "conversion": "145",
        "spend": "1800.0",
    },
}


def test_campaign_performance_maps_rows_purchase_value_and_budget() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["access-token"] == "tok-123"
        if str(request.url).startswith(_ADGROUP_URL):
            return _ok(
                [
                    {
                        "adgroup_id": "tt_1",
                        "budget": "80",
                        "budget_mode": "BUDGET_MODE_DAY",
                        "operation_status": "ENABLE",
                    }
                ]
            )
        assert str(request.url).startswith(_REPORT_URL)
        if "complete_payment" in request.url.params["metrics"]:
            return _ok(
                [
                    {
                        "dimensions": {"adgroup_id": "tt_1"},
                        "metrics": {"complete_payment": "3", "value_per_complete_payment": "150.5"},
                    }
                ]
            )
        return _ok([_ROW])

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    frame = provider.campaign_performance("adv_1")
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["arm_id"] == "tt_1"
    assert row["name"] == "Spark Ads"
    assert row["clicks"] == 3200
    assert row["conversions"] == 145
    assert row["cost"] == pytest.approx(1800.0)
    assert row["revenue"] == pytest.approx(451.5)
    assert row["daily_budget"] == 80
    assert row["budget_locked"] == ""
    assert bool(row["active"]) is True


def test_a_refused_purchase_value_or_budget_does_not_stop_the_plan() -> None:
    """Pixel fara evenimentul de cumparare, token fara drept pe grupuri: venit 0 (planul
    il valoreaza la cosul mediu) si bugetul neatins in noaptea asta."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_ADGROUP_URL) or "complete_payment" in str(
            request.url.params.get("metrics", "")
        ):
            return httpx.Response(200, json={"code": 40002, "message": "Invalid metric"})
        return _ok([_ROW])

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    row = provider.campaign_performance("adv_1").iloc[0]
    assert row["revenue"] == pytest.approx(0.0)
    assert row["daily_budget"] is None
    assert row["budget_locked"] == "bugetul de acum nu s-a putut citi"


def test_a_lifetime_or_campaign_budget_is_not_moved_per_group() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_ADGROUP_URL):
            return _ok(
                [
                    {
                        "adgroup_id": "tt_1",
                        "budget": "0",
                        "budget_mode": "BUDGET_MODE_INFINITE",
                        "operation_status": "ENABLE",
                    }
                ]
            )
        return _ok([_ROW] if "complete_payment" not in request.url.params["metrics"] else [])

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    row = provider.campaign_performance("adv_1").iloc[0]
    assert row["budget_locked"] == "buget pe campanie sau pe viata, nu zilnic pe grup"


def test_pagination_follows_total_page() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_ADGROUP_URL) or "complete_payment" in str(
            request.url.params.get("metrics", "")
        ):
            return _ok([])
        calls["count"] += 1
        page = int(request.url.params["page"])
        row = {
            "dimensions": {"adgroup_id": f"tt_{page}"},
            "metrics": {
                "adgroup_name": f"Group {page}",
                "clicks": "1",
                "conversion": "0",
                "spend": "1",
            },
        }
        return _ok([row], total_page=2, page=page)

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    frame = provider.campaign_performance("adv_1")
    assert calls["count"] == 2
    assert set(frame["arm_id"]) == {"tt_1", "tt_2"}


def test_auth_like_error_message_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 40100, "message": "Invalid access_token"})

    provider = LiveTikTokAdsProvider(
        access_token="bad-token", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("adv_1")


def test_other_api_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 40001, "message": "Invalid parameter format"})

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        provider.campaign_performance("adv_1")


def test_conversion_paths_single_touch_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "dimensions": {"adgroup_id": "tt_1"},
                            "metrics": {
                                "adgroup_name": "Spark",
                                "clicks": "4",
                                "conversion": "1",
                                "spend": "1",
                            },
                        }
                    ],
                    "page_info": {"page": 1, "total_page": 1},
                },
            },
        )

    provider = LiveTikTokAdsProvider(access_token="tok-123", transport=httpx.MockTransport(handler))
    paths = provider.conversion_paths("adv_1")
    assert len(paths) == 4
    assert sum(1 for p in paths if p[-1] == "conversion") == 1
