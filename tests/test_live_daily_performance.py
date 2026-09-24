"""Citirea zi-cu-zi de la Google Ads si Meta - sursa raportului saptamanal.

Fara retea: ``httpx.MockTransport``. Se verifica ce ar strica tacut un grafic:
intervalul cerut, data fiecarui rand si conversiile fractionare pastrate ca atare.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ppc_agent.decision.pipeline import SupportsDailyPerformance
from ppc_agent.errors import ProviderError
from ppc_agent.providers.live.daily import DAILY_COLUMNS, daily_window
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider

_OAUTH_URL = "https://oauth2.googleapis.com/token"


def test_fereastra_zilnica_se_termina_ieri_si_include_ambele_capete() -> None:
    start, end = daily_window(14, date(2026, 9, 20))
    assert (start, end) == (date(2026, 9, 7), date(2026, 9, 20))


def test_un_numar_de_zile_nepozitiv_e_refuzat() -> None:
    with pytest.raises(ProviderError):
        daily_window(0, date(2026, 9, 20))


def test_furnizorii_live_raporteaza_zi_cu_zi_iar_cei_mock_nu() -> None:
    """Mock-urile nu fabrica o serie zilnica dintr-un agregat - decizie a proiectului."""
    assert isinstance(LiveGoogleAdsProvider(), SupportsDailyPerformance)
    assert isinstance(LiveMetaMarketingProvider(), SupportsDailyPerformance)
    assert not isinstance(MockGoogleAdsProvider(), SupportsDailyPerformance)
    assert not isinstance(MockMetaMarketingProvider(), SupportsDailyPerformance)


def test_google_ads_cere_intervalul_exact_pe_segments_date() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == _OAUTH_URL:
            return httpx.Response(200, json={"access_token": "access-123"})
        queries.append(json.loads(request.content)["query"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "segments": {"date": "2026-09-19"},
                        "campaign": {"id": "11", "name": "Search - Brand"},
                        "metrics": {
                            "clicks": "40",
                            "conversions": 2.5,
                            "costMicros": "12340000",
                            "conversionsValue": 300.0,
                        },
                    }
                ]
            },
        )

    provider = LiveGoogleAdsProvider(
        developer_token="dev",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),
    )
    frame = provider.daily_campaign_performance("123", days=14, end_date=date(2026, 9, 20))

    assert "segments.date BETWEEN '2026-09-07' AND '2026-09-20'" in queries[0]
    assert list(frame.columns) == DAILY_COLUMNS
    row = frame.iloc[0]
    assert row["date"] == date(2026, 9, 19)
    assert row["cost"] == pytest.approx(12.34)
    assert row["conversions"] == 2.5  # fractionar, nu rotunjit


def test_meta_cere_zilele_cu_time_increment_si_time_range() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        seen.append({key: values[0] for key, values in query.items()})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "date_start": "2026-09-18",
                        "adset_id": "as_1",
                        "adset_name": "Retargeting",
                        "clicks": "30",
                        "spend": "25.10",
                        "actions": [
                            {"action_type": "purchase", "value": "2"},
                            {"action_type": "link_click", "value": "30"},
                        ],
                        "action_values": [{"action_type": "purchase", "value": "180.50"}],
                    }
                ],
                "paging": {},
            },
        )

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.daily_campaign_performance("act_555", days=7, end_date=date(2026, 9, 20))

    params = seen[0]
    assert params["time_increment"] == "1"
    assert json.loads(params["time_range"]) == {"since": "2026-09-14", "until": "2026-09-20"}
    assert params["level"] == "adset"
    row = frame.iloc[0]
    assert row["date"] == date(2026, 9, 18)
    assert row["conversions"] == 2.0  # doar "purchase", nu "link_click"
    assert row["revenue"] == pytest.approx(180.50)
    assert row["cost"] == pytest.approx(25.10)


def test_o_zi_fara_livrare_intoarce_tabel_gol_cu_coloanele_corecte() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "paging": {}})

    provider = LiveMetaMarketingProvider(
        access_token="token-123", transport=httpx.MockTransport(handler)
    )
    frame = provider.daily_campaign_performance("act_555", days=7, end_date=date(2026, 9, 20))
    assert frame.empty
    assert list(frame.columns) == DAILY_COLUMNS
