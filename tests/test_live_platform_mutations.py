"""Google Ads, TikTok si OpenAI Ads: citirea bugetelor si mutatiile, fara retea.

Fiecare test raspunde ca platforma reala (``httpx.MockTransport``) si verifica ce
cerere a plecat - forma ei e ce a aprobat omul.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from ppc_agent.config import AppConfig, Settings
from ppc_agent.errors import ProviderError
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.live.chatgpt_ads import LiveChatGptAdsMutations, LiveChatGptAdsProvider
from ppc_agent.providers.live.google_ads import (
    NEGATIVE_LIST_NAME,
    LiveGoogleAdsMutations,
    LiveGoogleAdsProvider,
)
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider, LiveTikTokMutations

_OAUTH_URL = "https://oauth2.googleapis.com/token"
_GOOGLE = "https://googleads.googleapis.com/v25/customers/1234567890"
_TIKTOK = "https://business-api.tiktok.com/open_api/v1.3"
_OPENAI = "https://api.ads.openai.com/v1"


class _Recorder:
    """Raspunde dupa (metoda, cale) si retine fiecare cerere, cu corpul ei JSON."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == _OAUTH_URL:
            return httpx.Response(200, json={"access_token": "access-123"})
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, url, body))
        answer = self.routes[(request.method, url)]
        payload = answer(body) if callable(answer) else answer
        return httpx.Response(200, json=payload)


# --- Google Ads ---------------------------------------------------------------------


def _google(routes: dict[tuple[str, str], Any]) -> tuple[LiveGoogleAdsMutations, _Recorder]:
    recorder = _Recorder(routes)
    reader = LiveGoogleAdsProvider(
        developer_token="dev",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(recorder),
    )
    return LiveGoogleAdsMutations(reader, "123-456-7890"), recorder


def _budget_row(*, shared: bool = False) -> dict[str, Any]:
    return {
        "results": [
            {
                "campaign": {"id": "555"},
                "campaignBudget": {
                    "resourceName": "customers/1234567890/campaignBudgets/88",
                    "amountMicros": "50000000",
                    "explicitlyShared": shared,
                    "period": "DAILY",
                },
            }
        ]
    }


def test_google_reads_the_daily_budget_and_changes_it_in_micros() -> None:
    mutations, recorder = _google(
        {
            ("POST", f"{_GOOGLE}/googleAds:search"): _budget_row(),
            ("POST", f"{_GOOGLE}/campaignBudgets:mutate"): {"results": [{}]},
        }
    )

    assert asyncio.run(mutations.current_daily_budget("555")) == Decimal("50.00")
    asyncio.run(mutations.update_campaign_budget("555", Decimal("60")))

    assert recorder.requests[-1] == (
        "POST",
        f"{_GOOGLE}/campaignBudgets:mutate",
        {
            "operations": [
                {
                    "updateMask": "amountMicros",
                    "update": {
                        "resourceName": "customers/1234567890/campaignBudgets/88",
                        "amountMicros": "60000000",
                    },
                }
            ]
        },
    )


def test_google_never_moves_a_budget_shared_with_other_campaigns() -> None:
    mutations, recorder = _google(
        {("POST", f"{_GOOGLE}/googleAds:search"): _budget_row(shared=True)}
    )

    assert asyncio.run(mutations.current_daily_budget("555")) is None
    with pytest.raises(ProviderError, match="partajat"):
        asyncio.run(mutations.update_campaign_budget("555", Decimal("60")))
    assert all(url.endswith("googleAds:search") for _, url, _ in recorder.requests)


def test_google_pauses_a_campaign_by_resource_name() -> None:
    mutations, recorder = _google({("POST", f"{_GOOGLE}/campaigns:mutate"): {"results": [{}]}})

    asyncio.run(mutations.pause_campaign("555"))

    [(_, _, body)] = recorder.requests
    assert body["operations"][0] == {
        "updateMask": "status",
        "update": {"resourceName": "customers/1234567890/campaigns/555", "status": "PAUSED"},
    }


def test_google_rejects_a_campaign_id_that_is_not_a_number() -> None:
    mutations, recorder = _google({})
    with pytest.raises(ProviderError, match="invalid"):
        asyncio.run(mutations.pause_campaign("555 OR 1=1"))
    assert recorder.requests == []


def test_a_negative_keyword_creates_the_account_list_and_attaches_it_once() -> None:
    shared_set = "customers/1234567890/sharedSets/42"

    def search(body: dict[str, Any]) -> dict[str, Any]:
        query = body["query"]
        if "FROM shared_set " in query:
            return {"results": []}  # lista nu exista inca
        if "FROM shared_criterion" in query:
            return {"results": []}
        if "FROM campaign_shared_set" in query:
            return {
                "results": [{"campaignSharedSet": {"campaign": "customers/1234567890/campaigns/1"}}]
            }
        return {
            "results": [
                {"campaign": {"resourceName": "customers/1234567890/campaigns/1"}},
                {"campaign": {"resourceName": "customers/1234567890/campaigns/2"}},
            ]
        }

    mutations, recorder = _google(
        {
            ("POST", f"{_GOOGLE}/googleAds:search"): search,
            ("POST", f"{_GOOGLE}/sharedSets:mutate"): {"results": [{"resourceName": shared_set}]},
            ("POST", f"{_GOOGLE}/sharedCriteria:mutate"): {"results": [{}]},
            ("POST", f"{_GOOGLE}/campaignSharedSets:mutate"): {"results": [{}]},
        }
    )

    asyncio.run(mutations.add_negative_keyword("gratuit", "phrase"))

    mutated = {
        url.rsplit("/", 1)[1]: body for method, url, body in recorder.requests if "mutate" in url
    }
    assert mutated["sharedSets:mutate"]["operations"] == [
        {"create": {"name": NEGATIVE_LIST_NAME, "type": "NEGATIVE_KEYWORDS"}}
    ]
    assert mutated["sharedCriteria:mutate"]["operations"] == [
        {"create": {"sharedSet": shared_set, "keyword": {"text": "gratuit", "matchType": "PHRASE"}}}
    ]
    # Campania 1 avea deja lista: doar campania 2 se ataseaza.
    assert mutated["campaignSharedSets:mutate"]["operations"] == [
        {"create": {"campaign": "customers/1234567890/campaigns/2", "sharedSet": shared_set}}
    ]


def test_a_negative_already_in_the_list_is_not_added_twice() -> None:
    shared_set = "customers/1234567890/sharedSets/42"

    def search(body: dict[str, Any]) -> dict[str, Any]:
        query = body["query"]
        if "FROM shared_set " in query:
            return {"results": [{"sharedSet": {"resourceName": shared_set}}]}
        if "FROM shared_criterion" in query:
            return {
                "results": [
                    {"sharedCriterion": {"keyword": {"text": "Gratuit", "matchType": "PHRASE"}}}
                ]
            }
        return {"results": []}

    mutations, recorder = _google({("POST", f"{_GOOGLE}/googleAds:search"): search})

    asyncio.run(mutations.add_negative_keyword("gratuit", "phrase"))

    assert not [url for _, url, _ in recorder.requests if "mutate" in url]


def test_google_reports_the_campaign_budget_and_why_it_cannot_move() -> None:
    row = {
        "campaign": {"id": "1", "name": "Search", "status": "ENABLED", "primaryStatus": "LEARNING"},
        "campaignBudget": {
            "amountMicros": "40000000",
            "explicitlyShared": False,
            "period": "DAILY",
        },
        "metrics": {"clicks": "10", "conversions": 1, "costMicros": "5000000"},
    }
    paused = {
        "campaign": {"id": "2", "name": "Vechi", "status": "PAUSED"},
        "campaignBudget": {"amountMicros": "10000000", "explicitlyShared": True},
        "metrics": {"clicks": "1"},
    }
    recorder = _Recorder({("POST", f"{_GOOGLE}/googleAds:search"): {"results": [row, paused]}})
    reader = LiveGoogleAdsProvider(
        developer_token="dev",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(recorder),
    )

    frame = reader.campaign_performance("1234567890").set_index("arm_id")

    assert frame.loc["1", "daily_budget"] == Decimal("40.00")
    assert frame.loc["1", "budget_locked"] == "strategia de licitare e in invatare"
    assert bool(frame.loc["2", "active"]) is False
    assert frame.loc["2", "budget_locked"] == "buget partajat cu alte campanii"


def test_a_conversion_google_refuses_comes_back_as_an_error() -> None:
    recorder = _Recorder(
        {
            ("POST", f"{_GOOGLE}:uploadClickConversions"): {
                "partialFailureError": {"code": 3, "message": "The click could not be found."}
            }
        }
    )
    reader = LiveGoogleAdsProvider(
        developer_token="dev",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(recorder),
    )

    with pytest.raises(ProviderError, match="click could not be found"):
        reader.upload_click_conversion("1234567890", {"gclid": "abc"})
    [(_, _, body)] = recorder.requests
    assert body == {"conversions": [{"gclid": "abc"}], "partialFailure": True}


# --- TikTok -------------------------------------------------------------------------


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 0, "message": "OK", "data": data}


def _tiktok(routes: dict[tuple[str, str], Any]) -> tuple[LiveTikTokMutations, _Recorder]:
    recorder = _Recorder(routes)
    reader = LiveTikTokAdsProvider(access_token="tok", transport=httpx.MockTransport(recorder))
    return LiveTikTokMutations(reader, "adv_1"), recorder


def _adgroup(mode: str) -> dict[str, Any]:
    return _ok(
        {
            "list": [{"adgroup_id": "9", "budget": 80.0, "budget_mode": mode}],
            "page_info": {"total_page": 1},
        }
    )


def test_tiktok_changes_a_daily_ad_group_budget() -> None:
    mutations, recorder = _tiktok(
        {
            ("GET", f"{_TIKTOK}/adgroup/get/"): _adgroup("BUDGET_MODE_DAY"),
            ("POST", f"{_TIKTOK}/adgroup/update/"): _ok({}),
        }
    )

    asyncio.run(mutations.update_adgroup_budget("9", Decimal("64")))

    assert recorder.requests[-1] == (
        "POST",
        f"{_TIKTOK}/adgroup/update/",
        {"advertiser_id": "adv_1", "adgroup_id": "9", "budget": 64.0},
    )


def test_tiktok_leaves_a_campaign_or_lifetime_budget_alone() -> None:
    mutations, recorder = _tiktok(
        {("GET", f"{_TIKTOK}/adgroup/get/"): _adgroup("BUDGET_MODE_INFINITE")}
    )

    with pytest.raises(ProviderError, match="buget zilnic propriu"):
        asyncio.run(mutations.update_adgroup_budget("9", Decimal("64")))
    assert [method for method, _, _ in recorder.requests] == ["GET"]


def test_tiktok_pauses_ad_groups_and_ads() -> None:
    mutations, recorder = _tiktok(
        {
            ("POST", f"{_TIKTOK}/adgroup/status/update/"): _ok({}),
            ("POST", f"{_TIKTOK}/ad/status/update/"): _ok({}),
        }
    )

    asyncio.run(mutations.pause_adgroup("9"))
    asyncio.run(mutations.pause_ad("77"))

    assert [body for _, _, body in recorder.requests] == [
        {"advertiser_id": "adv_1", "adgroup_ids": ["9"], "operation_status": "DISABLE"},
        {"advertiser_id": "adv_1", "ad_ids": ["77"], "operation_status": "DISABLE"},
    ]


def test_tiktok_reads_the_account_currency() -> None:
    mutations, _ = _tiktok(
        {("GET", f"{_TIKTOK}/advertiser/info/"): _ok({"list": [{"currency": "RON"}]})}
    )
    assert asyncio.run(mutations.account_currency()) == "RON"


# --- OpenAI Ads (ChatGPT) -----------------------------------------------------------


def _openai(routes: dict[tuple[str, str], Any]) -> tuple[LiveChatGptAdsProvider, _Recorder]:
    recorder = _Recorder(routes)
    return LiveChatGptAdsProvider(api_key="key", transport=httpx.MockTransport(recorder)), recorder


def test_chatgpt_campaigns_become_plan_arms_with_sales_and_budget() -> None:
    reader, recorder = _openai(
        {
            ("GET", f"{_OPENAI}/campaigns"): {
                "data": [
                    {
                        "id": "cmpn_1",
                        "name": "Intrebari despre service",
                        "status": "active",
                        "budget": {"daily_spend_limit_micros": 75000000},
                    },
                    {
                        "id": "cmpn_2",
                        "name": "Lansare",
                        "status": "paused",
                        "budget": {"lifetime_spend_limit_micros": 30000000},
                    },
                ],
                "has_more": False,
            },
            ("GET", f"{_OPENAI}/ad_account/insights"): {
                "data": [{"campaign_id": "cmpn_1", "clicks": 120, "spend": 300.5}],
                "has_more": False,
            },
            ("POST", f"{_OPENAI}/conversions/insights"): {
                "data": [
                    {
                        "entity_id": "cmpn_1",
                        "conversions": 6,
                        "order_created_attributed_sales": "900.00",
                    }
                ]
            },
        }
    )

    frame = reader.campaign_performance().set_index("arm_id")

    assert frame.loc["cmpn_1", "clicks"] == 120
    assert frame.loc["cmpn_1", "cost"] == pytest.approx(300.5)
    assert frame.loc["cmpn_1", "conversions"] == 6
    assert frame.loc["cmpn_1", "revenue"] == pytest.approx(900.0)
    assert frame.loc["cmpn_1", "daily_budget"] == Decimal("75.00")
    assert bool(frame.loc["cmpn_2", "active"]) is False
    assert frame.loc["cmpn_2", "budget_locked"] == "buget pe viata, nu zilnic"
    _, _, body = recorder.requests[-1]
    assert body["aggregation_level"] == "campaign"


def test_chatgpt_daily_budget_and_pause() -> None:
    campaign = {"id": "cmpn_1", "budget": {"daily_spend_limit_micros": 75000000}}
    reader, recorder = _openai(
        {
            ("GET", f"{_OPENAI}/campaigns/cmpn_1"): campaign,
            ("POST", f"{_OPENAI}/campaigns/cmpn_1"): campaign,
            ("POST", f"{_OPENAI}/campaigns/cmpn_1/pause"): campaign,
        }
    )
    mutations = LiveChatGptAdsMutations(reader)

    assert asyncio.run(mutations.current_daily_budget("cmpn_1")) == Decimal("75.00")
    asyncio.run(mutations.update_campaign_budget("cmpn_1", Decimal("60")))
    asyncio.run(mutations.pause_campaign("cmpn_1"))

    posts = [(url, body) for method, url, body in recorder.requests if method == "POST"]
    assert posts == [
        (f"{_OPENAI}/campaigns/cmpn_1", {"budget": {"daily_spend_limit_micros": 60000000}}),
        (f"{_OPENAI}/campaigns/cmpn_1/pause", None),
    ]


def test_chatgpt_has_no_mock_data_so_it_stays_out_of_the_mock_plan() -> None:
    factory = ProviderFactory(AppConfig(settings=Settings(_env_file=None)))
    assert factory.configured("chatgpt_ads") is False
    assert factory.chatgpt_mutations() is None
    assert factory.google_ads_mutations() is None
    assert factory.tiktok_mutations() is None
