"""``GET /api/v1/seo/intelligence`` - trafic, pozitii si recomandari pentru client.

Fara retea: Google e un ``httpx.MockTransport`` injectat prin aceleasi dependinte
ca Integrarile, iar "azi" e fixat. Se verifica alegerea surselor, care e partea
riscanta: demo doar pentru ce NU e conectat, niciodata in locul unei surse
conectate care pica.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.search_data.google_oauth import OAUTH_TOKEN_URL
from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.routers import integrations, seo_intelligence
from ppc_agent_server.security import encrypt_secret

_TODAY = date(2026, 9, 24)
_WINDOW_END = date(2026, 9, 21)  # azi minus intarzierea datelor Search Console


def _days(body: dict[str, Any]) -> list[date]:
    # Search Console trimite startDate/endDate; GA4, dateRanges.
    period = body["dateRanges"][0] if "dateRanges" in body else body
    start = date.fromisoformat(period["startDate"])
    end = date.fromisoformat(period["endDate"])
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _google(request: httpx.Request) -> httpx.Response:
    """Google simulat: OAuth, Search Console si GA4, cu cifre fixe pe zi."""
    if str(request.url) == OAUTH_TOKEN_URL:
        return httpx.Response(200, json={"access_token": "access"})
    body = json.loads(request.content)
    if request.url.host == "www.googleapis.com":  # Search Console
        if body["dimensions"] == ["date"]:
            rows = [
                {"keys": [day.isoformat()], "clicks": 20, "impressions": 500, "position": 6.0}
                for day in _days(body)
            ]
        else:
            rows = [
                {
                    "keys": ["schimb ulei", "https://exemplu.ro/ulei"],
                    "clicks": 30,
                    "impressions": 1200,
                    "position": 4.0,
                },
                {
                    "keys": ["schimb ulei", "https://exemplu.ro/blog"],
                    "clicks": 2,
                    "impressions": 100,
                    "position": 9.0,
                },
            ]
        return httpx.Response(200, json={"rows": rows})
    # GA4 Data API
    dimension = body["dimensions"][0]["name"]
    metrics = [metric["name"] for metric in body["metrics"]]
    if dimension == "date":
        values = [[day.strftime("%Y%m%d"), "100", "180", "60"] for day in _days(body)]
    else:
        values = [["/", "2000", "1300"], ["/ulei", "900", "500"]]
    return httpx.Response(
        200,
        json={
            "dimensionHeaders": [{"name": dimension}],
            "metricHeaders": [{"name": name} for name in metrics],
            "rows": [
                {
                    "dimensionValues": [{"value": row[0]}],
                    "metricValues": [{"value": value} for value in row[1:]],
                }
                for row in values
            ],
        },
    )


@pytest.fixture
def signed_in(
    client: TestClient, agency_settings: Tenant
) -> Iterator[tuple[TestClient, FastAPI, dict[str, str], int]]:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[seo_intelligence.get_today] = lambda: _TODAY
    app.dependency_overrides[integrations.get_google_oauth_client] = lambda: (
        integrations.GoogleOAuthClient(client_id="client-123", client_secret="secret")
    )
    app.dependency_overrides[integrations.get_google_transport] = lambda: httpx.MockTransport(
        _google
    )
    token = client.post(
        "/api/v1/signup",
        json={"name": "Exemplu", "email": "client@exemplu.ro", "password": "parola-sigura-123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = int(client.get("/api/v1/me", headers=headers).json()["account"]["id"])
    yield client, app, headers, account_id
    app.dependency_overrides.clear()


def _connect(session: Session, account_id: int, *, gsc: bool = False, ga4: bool = False) -> None:
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.target_domain = "https://exemplu.ro"
    if gsc:
        account.gsc_refresh_token_enc = encrypt_secret("refresh-gsc")
        account.gsc_site_url = "sc-domain:exemplu.ro"
    if ga4:
        account.ga4_refresh_token_enc = encrypt_secret("refresh-ga4")
        account.ga4_property_id = "123456789"
    session.add(account)
    session.commit()


def _statuses(body: dict[str, Any]) -> dict[str, str]:
    return {source["key"]: source["status"] for source in body["sources"]}


def test_fara_conexiuni_pagina_arata_date_demonstrative_marcate(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    response = client.get("/api/v1/seo/intelligence", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_demo"] is True
    assert _statuses(body) == {"ga4": "demo", "gsc": "demo", "keyword_planner": "demo"}
    assert body["period"] == {"start": "2026-08-25", "end": "2026-09-21", "days": 28}
    assert len(body["timeseries"]) == 28
    assert body["keywords"] and body["ai_recommendations"]
    assert body["recommendations_engine"] == "rules"


def test_perioada_e_de_7_28_sau_90_de_zile(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    week = client.get("/api/v1/seo/intelligence", headers=headers, params={"days": 7})
    assert len(week.json()["timeseries"]) == 7
    invalid = client.get("/api/v1/seo/intelligence", headers=headers, params={"days": 14})
    assert invalid.status_code == 422


def test_cu_gsc_si_ga4_conectate_datele_sunt_ale_clientului(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    _connect(session, account_id, gsc=True, ga4=True)

    body = client.get("/api/v1/seo/intelligence", headers=headers).json()

    assert body["is_demo"] is False
    statuses = _statuses(body)
    assert (statuses["ga4"], statuses["gsc"]) == ("live", "live")
    # Mock-ul Keyword Planner ar pune volume inventate langa date reale.
    assert statuses["keyword_planner"] == "not_connected"
    day = body["timeseries"][-1]
    assert day["date"] == _WINDOW_END.isoformat()
    assert (day["sessions"], day["pageviews"], day["engagement_rate"]) == (100, 180, 0.6)
    assert (day["clicks"], day["impressions"], day["position"]) == (20, 500, 6.0)
    (keyword,) = body["keywords"]
    assert keyword["keyword"] == "schimb ulei"
    assert (keyword["clicks"], keyword["impressions"]) == (32, 1300)
    # Pagina pastrata e cea cu cele mai multe afisari pentru cuvant.
    assert keyword["url"] == "https://exemplu.ro/ulei"
    assert keyword["position"] == round((4.0 * 1200 + 9.0 * 100) / 1300, 1)
    assert body["domain"] == "exemplu.ro"


def test_o_sursa_conectata_dar_inutilizabila_nu_devine_demo(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    """Fara client OAuth, token-ul GSC nu se poate folosi - dar nici nu se inlocuieste."""
    client, app, headers, account_id = signed_in
    _connect(session, account_id, gsc=True)
    app.dependency_overrides[integrations.get_google_oauth_client] = lambda: None

    body = client.get("/api/v1/seo/intelligence", headers=headers).json()
    statuses = _statuses(body)

    assert statuses["gsc"] == "unavailable"
    assert statuses["ga4"] == "demo"  # GA4 nu e conectat: demo, marcat
    assert all(point["clicks"] is None for point in body["timeseries"])
    assert body["keywords"] == []
    notes = {source["key"]: source["note"] for source in body["sources"]}
    assert "OAuth" in notes["gsc"]


def test_pagina_cere_autentificare(client: TestClient) -> None:
    assert client.get("/api/v1/seo/intelligence").status_code == 401
