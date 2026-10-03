"""Teste deterministe pentru LiveMetaMarketingProvider, fara retea reala.

Foloseste ``httpx.MockTransport`` (acelasi pattern ca ``test_llm_live.py``).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from urllib.parse import parse_qsl

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider

_ADSETS_URL = "https://graph.facebook.com/v25.0/act_999/adsets"
_INSIGHTS_URL = "https://graph.facebook.com/v25.0/act_999/insights"


def test_missing_access_token_raises_without_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveMetaMarketingProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("act_999")


def test_campaign_performance_sums_conversion_actions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token-123"
        if str(request.url).startswith(_ADSETS_URL):
            return httpx.Response(
                200, json={"data": [{"id": "as_1", "effective_status": "ACTIVE"}], "paging": {}}
            )
        assert str(request.url).startswith(_INSIGHTS_URL)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "adset_id": "as_1",
                        "adset_name": "Retargeting",
                        "clicks": "200",
                        "spend": "150.50",
                        "actions": [
                            {"action_type": "purchase", "value": "10"},
                            {"action_type": "link_click", "value": "999"},
                        ],
                        "action_values": [{"action_type": "purchase", "value": "500.0"}],
                    }
                ],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.campaign_performance("act_999")
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["arm_id"] == "as_1"
    assert row["clicks"] == 200
    assert row["conversions"] == 10  # doar "purchase", nu "link_click"
    assert row["cost"] == pytest.approx(150.50)
    assert row["revenue"] == pytest.approx(500.0)
    assert bool(row["active"]) is True


def test_same_purchase_reported_under_three_types_counts_once() -> None:
    """Meta raporteaza aceleasi 10 cumparari ca purchase, omni_purchase si pixel: nu 30."""
    sent: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(parse_qsl(request.url.query.decode()))
        kinds = ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "adset_id": "as_1",
                        "clicks": "800",
                        "spend": "1000",
                        # "value" include si view-through; se ia fereastra de 7 zile la click
                        "actions": [
                            *({"action_type": t, "value": "12", "7d_click": "10"} for t in kinds),
                            {"action_type": "lead", "value": "4"},
                            {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
                        ],
                        "action_values": [
                            {"action_type": t, "value": "1800", "7d_click": "1500"} for t in kinds
                        ],
                    }
                ],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    row = provider.campaign_performance("act_999").iloc[0]
    assert row["conversions"] == 14  # 10 cumparari + 4 lead-uri, fiecare o data
    assert row["revenue"] == pytest.approx(1500.0)
    assert sent["action_attribution_windows"] == '["7d_click"]'


def test_ad_sets_merges_adsets_and_insights() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(_ADSETS_URL):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "as_1",
                            "name": "PFA 25-34",
                            "targeting": {
                                "age_min": 25,
                                "age_max": 34,
                                "geo_locations": {"countries": ["RO"]},
                            },
                            "learning_stage_info": {"status": "LEARNING"},
                            "daily_budget": "2550",  # in bani, ca la scriere
                        }
                    ],
                    "paging": {},
                },
            )
        assert url.startswith(_INSIGHTS_URL)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "adset_id": "as_1",
                        "spend": "180.0",
                        "actions": [{"action_type": "lead", "value": "12"}],
                    }
                ],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.ad_sets("act_999")
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["ad_set_id"] == "as_1"
    assert row["weekly_conversions"] == pytest.approx(12.0)
    assert row["weekly_spend"] == pytest.approx(180.0)
    assert bool(row["learning_phase"]) is True
    assert row["learning_status"] == "LEARNING"
    assert row["daily_budget"] == pytest.approx(25.50)
    assert "25" in row["audience_def"] and "ro" in row["audience_def"]


def test_pagination_follows_paging_next() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_ADSETS_URL):  # starea seturilor, o pagina
            return httpx.Response(200, json={"data": [], "paging": {}})
        calls["count"] += 1
        if calls["count"] == 1:
            assert str(request.url).startswith(_INSIGHTS_URL)
            return httpx.Response(
                200,
                json={
                    "data": [{"adset_id": "a", "adset_name": "A", "clicks": "1", "spend": "1"}],
                    "paging": {"next": _INSIGHTS_URL + "?after=cursor2"},
                },
            )
        assert "after=cursor2" in str(request.url)
        return httpx.Response(
            200,
            json={
                "data": [{"adset_id": "b", "adset_name": "B", "clicks": "2", "spend": "2"}],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.campaign_performance("act_999")
    assert calls["count"] == 2
    assert set(frame["arm_id"]) == {"a", "b"}


def test_oauth_error_code_190_raises_setup_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": {"code": 190, "message": "Error validating access token"}}
        )

    provider = LiveMetaMarketingProvider(
        access_token="expired-token", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SetupRequiredError):
        provider.campaign_performance("act_999")


def test_other_api_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 100, "message": "Invalid parameter"}})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError):
        provider.campaign_performance("act_999")


def test_conversion_paths_single_touch_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "adset_id": "a",
                        "adset_name": "A",
                        "clicks": "5",
                        "spend": "1",
                        "actions": [{"action_type": "purchase", "value": "2"}],
                        "action_values": [{"action_type": "purchase", "value": "20"}],
                    }
                ],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    paths = provider.conversion_paths("act_999")
    assert len(paths) == 5
    assert sum(1 for p in paths if p[-1] == "conversion") == 2


# --- mutatii (scriere) ------------------------------------------------------
#
# Aici se schimba ceva real intr-un cont platit, deci testele merg pe transportul
# httpx (MockTransport), nu pe metode inlocuite: asa trece si constructia URL-ului,
# si serializarea corpului, si tratarea codului de raspuns.

_MUTATION_URL = "https://graph.facebook.com/v25.0/23848"


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def test_pause_adset_posts_paused_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == _MUTATION_URL
        assert request.headers["authorization"] == "Bearer token-123"
        assert dict(parse_qsl(request.content.decode())) == {"status": "PAUSED"}
        return httpx.Response(200, json={"success": True})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    _run(provider.pause_adset("23848"))


def test_update_budget_sends_minor_units() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(parse_qsl(request.content.decode())) == {"daily_budget": "2550"}
        return httpx.Response(200, json={"success": True})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    _run(provider.update_budget("23848", Decimal("25.50")))


def test_update_budget_does_not_multiply_zero_decimal_currencies() -> None:
    """Pe HUF, x100 ar trimite un buget de 100 de ori mai mare."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(parse_qsl(request.content.decode())) == {"daily_budget": "2550"}
        return httpx.Response(200, json={"success": True})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", currency="HUF", transport=httpx.MockTransport(handler)
    )
    _run(provider.update_budget("23848", Decimal("2550")))


def test_negative_budget_never_reaches_the_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="negativ"):
        _run(provider.update_budget("23848", Decimal("-1")))


def test_empty_object_id_never_reaches_the_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="gol"):
        _run(provider.pause_campaign("   "))


def test_mutation_without_token_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveMetaMarketingProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SetupRequiredError):
        _run(provider.pause_adset("23848"))


def test_meta_rejection_keeps_its_own_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Invalid parameter", "code": 100}}
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="Invalid parameter"):
        _run(provider.pause_adset("23848"))


def test_expired_token_is_setup_not_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Session has expired", "code": 190}}
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SetupRequiredError, match="reconecteaza"):
        _run(provider.pause_adset("23848"))


def test_error_in_a_200_body_is_not_success() -> None:
    """Graph API poate raspunde 200 cu "error" in corp - nu e o schimbare aplicata."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"message": "Nothing changed", "code": 2}})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="Nothing changed"):
        _run(provider.pause_adset("23848"))


def test_paused_ad_sets_keep_their_history_but_are_marked_inactive() -> None:
    """Un set oprit a cheltuit luna asta: ramane in cifre (CFO), dar nu mai e "activ"."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_ADSETS_URL):
            sets = [
                {"id": "as_on", "effective_status": "ACTIVE"},
                {"id": "as_off", "effective_status": "PAUSED"},
            ]
            return httpx.Response(200, json={"data": sets, "paging": {}})
        rows = [
            {"adset_id": set_id, "clicks": "10", "spend": "50"} for set_id in ("as_on", "as_off")
        ]
        return httpx.Response(200, json={"data": rows, "paging": {}})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.campaign_performance("act_999")
    assert dict(zip(frame["arm_id"], frame["active"], strict=True)) == {
        "as_on": True,
        "as_off": False,
    }


def test_ad_insights_reads_running_ads_for_the_fatigue_monitor() -> None:
    """Lista anunturilor + cifrele celor active: de la lansare, frecventa, zi cu zi."""
    seen: list[dict[str, str]] = []
    purchase = ("purchase", "omni_purchase")

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.url.query.decode()))
        seen.append(params)
        if request.url.path.endswith("/ads"):
            ads = [
                {"id": "a1", "name": "Video", "created_time": "2026-09-20T10:00:00+0300",
                 "effective_status": "ACTIVE"},
                {"id": "a2", "name": "Oprit", "created_time": "2026-09-01T10:00:00+0300",
                 "effective_status": "PAUSED"},
            ]
            return httpx.Response(200, json={"data": ads, "paging": {}})
        if params.get("date_preset") == "maximum":
            row = {
                "ad_id": "a1", "spend": "120.50", "impressions": "3000", "clicks": "45",
                "actions": [{"action_type": t, "value": "3", "7d_click": "2"} for t in purchase],
                "action_values": [
                    {"action_type": t, "value": "300", "7d_click": "200"} for t in purchase
                ],
            }
            return httpx.Response(200, json={"data": [row], "paging": {}})
        if params.get("date_preset") == "last_7d":
            return httpx.Response(200, json={"data": [{"ad_id": "a1", "frequency": "2.4"}]})
        day = {
            "ad_id": "a1", "date_start": "2026-10-01", "spend": "10", "impressions": "300",
            "clicks": "5", "actions": [{"action_type": "purchase", "value": "1"}],
        }
        return httpx.Response(200, json={"data": [day], "paging": {}})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    running, paused = provider.ad_insights("act_999")

    assert (running.ad_id, running.active, running.spend, running.impressions) == (
        "a1", True, 120.5, 3000
    )
    assert (running.conversions, running.revenue) == (2.0, 200.0)  # o data, 7 zile la click
    assert running.frequency_7d == pytest.approx(2.4)
    assert [(day.day.isoformat(), day.conversions) for day in running.days] == [
        ("2026-10-01", 1.0)
    ]
    assert running.created_time.utcoffset() is not None
    assert (paused.ad_id, paused.active, paused.spend) == ("a2", False, 0.0)
    # Cifrele se cer doar pentru anunturile care ruleaza.
    insights = [params for params in seen if "level" in params]
    assert len(insights) == 3
    assert all("ACTIVE" in params["filtering"] for params in insights)
