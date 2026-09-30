"""Clientul GA4 (Data API runReport) si perechile cuvant-pagina din Search Console.

Fara retea: ``httpx.MockTransport``. Se verifica ce ar strica tacut graficele:
data GA4 ("20260920") citita gresit, randul "(not set)" luat drept pagina, o
proprietate fara acces raportata ca eroare de server in loc de problema de
configurare pe care o rezolva clientul.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.search_data.analytics import AnalyticsDataClient, DailyTotals, LandingPageTotals
from ppc_agent.search_data.google_oauth import OAUTH_TOKEN_URL
from ppc_agent.search_data.search_console import QueryPageTotals, SearchConsoleClient

_START, _END = date(2026, 9, 1), date(2026, 9, 21)


def _client(handler: Any, **kwargs: Any) -> AnalyticsDataClient:
    return AnalyticsDataClient(
        property_id=kwargs.pop("property_id", "properties/123456789"),
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),
    )


def _report(dimension: str, metrics: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {
        "dimensionHeaders": [{"name": dimension}],
        "metricHeaders": [{"name": name, "type": "TYPE_INTEGER"} for name in metrics],
        "rows": [
            {
                "dimensionValues": [{"value": row[0]}],
                "metricValues": [{"value": value} for value in row[1:]],
            }
            for row in rows
        ],
    }


def test_traficul_zilnic_se_cere_pe_proprietate_si_se_citeste_corect() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "access-ga4"})
        requests.append(request)
        return httpx.Response(
            200,
            json=_report(
                "date",
                ["sessions", "screenPageViews", "engagedSessions"],
                [["20260920", "120", "245", "80"], ["20260921", "98", "190", "61"]],
            ),
        )

    rows = _client(handler).daily_totals(start_date=_START, end_date=_END)

    assert rows == [
        DailyTotals(date(2026, 9, 20), 120, 245, 80),
        DailyTotals(date(2026, 9, 21), 98, 190, 61),
    ]
    request = requests[0]
    assert request.url.path == "/v1beta/properties/123456789:runReport"
    assert request.headers["authorization"] == "Bearer access-ga4"
    body = json.loads(request.content)
    assert body["dateRanges"] == [{"startDate": "2026-09-01", "endDate": "2026-09-21"}]
    assert [metric["name"] for metric in body["metrics"]] == [
        "sessions",
        "screenPageViews",
        "engagedSessions",
    ]


def test_paginile_de_intrare_fara_randul_not_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "a"})
        body = json.loads(request.content)
        assert body["orderBys"] == [{"metric": {"metricName": "sessions"}, "desc": True}]
        return httpx.Response(
            200,
            json=_report(
                "landingPage",
                ["sessions", "engagedSessions"],
                [["/", "500", "320"], ["(not set)", "40", "0"], ["/preturi", "120", "30"]],
            ),
        )

    pages = _client(handler).landing_pages(start_date=_START, end_date=_END)
    assert pages == [LandingPageTotals("/", 500, 320), LandingPageTotals("/preturi", 120, 30)]


def test_o_proprietate_fara_acces_e_o_problema_de_configurare() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "a"})
        return httpx.Response(403, json={"error": {"message": "User does not have access"}})

    with pytest.raises(SetupRequiredError, match="refuza accesul"):
        _client(handler).daily_totals(start_date=_START, end_date=_END)


def test_fara_proprietate_nu_se_face_nicio_cerere() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu trebuia sa ajunga la retea")

    with pytest.raises(SetupRequiredError, match="nu e aleasa"):
        _client(handler, property_id="").daily_totals(start_date=_START, end_date=_END)


def test_search_console_da_cuvintele_impreuna_cu_pagina_lor() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "a"})
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["schimb ulei", "https://exemplu.ro/ulei"],
                        "clicks": 12,
                        "impressions": 900,
                        "ctr": 0.013,
                        "position": 4.2,
                    },
                    {"keys": ["malformat"], "clicks": 1, "impressions": 1},
                ]
            },
        )

    client = SearchConsoleClient(
        site_url="sc-domain:exemplu.ro",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),
    )
    rows = client.fetch_query_pages(start_date=_START, end_date=_END)

    assert rows == [QueryPageTotals("schimb ulei", "https://exemplu.ro/ulei", 12, 900, 4.2)]
    assert bodies[0]["dimensions"] == ["query", "page"]


def _ga_body(body: str) -> AnalyticsDataClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "a"})
        return httpx.Response(200, text=body, headers={"content-type": "application/json"})

    return _client(handler)


# Un 200 cu JSON valid dar de alta forma (proxy corupt, schimbare de API) nu trebuie sa
# scoata AttributeError/KeyError - Regina citeste traficul cu try/except pe PpcAgentError.
@pytest.mark.parametrize(
    "body",
    [
        '{"rows": [1, "x", null]}',  # randuri care nu sunt obiecte
        '{"rows": "abc"}',  # "rows" nu e lista
        '{"rows": [{"keys": [1]}]}',  # randuri fara antete => fara coloane
        '{"rows": [{}]}',
    ],
)
def test_ga4_cu_raspuns_de_alta_forma_da_trafic_gol_nu_crapa(body: str) -> None:
    assert _ga_body(body).channel_sessions(start_date=_START, end_date=_END) == {}


@pytest.mark.parametrize("body", ["[1, 2, 3]", "null", '"doar un string"'])
def test_ga4_cu_raspuns_care_nu_e_obiect_e_o_eroare_de_furnizor(body: str) -> None:
    with pytest.raises(ProviderError, match="nu e un obiect JSON"):
        _ga_body(body).channel_sessions(start_date=_START, end_date=_END)
