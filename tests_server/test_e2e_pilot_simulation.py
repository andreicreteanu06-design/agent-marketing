"""Pilotul Meta simulat, cap-coada, pe date fictive - de rulat inainte de o lansare.

Serverul ruleaza in mod ``live`` real (aprobari, motorul de executie, Conversions API),
dar NICIO cerere nu pleaca spre Meta: tot ce merge la graph.facebook.com e interceptat
si raspuns local, iar imaginea reclamei e fictiva. Un singur scenariu, in ordine:

1. clientul se inscrie, agentia ii seteaza pixelul;
2. o comanda Gomag pleaca la CAPI o singura data (``event_id``, PII hash-uit, cod de test);
3. webhook-ul retrimis se deduplica; un apel de 12 s nu ajunge la Meta;
4. pauza, buget si lansare (OPRITA) trec in plafon; bugetul ajunge in bani;
5. peste ``MAX_DAILY_SPEND_RON``: 409, nimic trimis, alerta CRITICAL; o pauza trece oricum;
6. un cont Meta in EUR e refuzat.

Rulare (sare implicit, ca suita obisnuita sa ramana rapida) - vezi si README,
«Inainte de pilotul Meta»:

    $env:PILOT_E2E = "1"
    .venv\\Scripts\\python.exe -m pytest tests_server/test_e2e_pilot_simulation.py -v
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent_server.models import ChangeOp, ChangeStatus, ConversionEvent, ProposedChange, Tenant
from ppc_agent_server.settings import get_server_settings
from tests_server.test_campaign_launch import _spec

pytestmark = pytest.mark.skipif(
    os.environ.get("PILOT_E2E") != "1",
    reason="pilotul simulat ruleaza doar cu PILOT_E2E=1 (inainte de o lansare)",
)

PIXEL = "998877665544332"
AD_ACCOUNT = "act_111222333"
TEST_CODE = "TEST12345"


class _FakeMeta:
    """graph.facebook.com, local: retine fiecare cerere si raspunde ca Meta."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._ids = iter(range(120_000_000_001, 120_000_009_999))

    def answer(self, url: str, data: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "data": data})
        request = httpx.Request("POST", url)
        if url.endswith("/events"):  # Conversions API
            return httpx.Response(200, json={"events_received": 1}, request=request)
        if url.endswith("/adimages"):
            return httpx.Response(
                200, json={"images": {"reclama.jpg": {"hash": "hashfictiv"}}}, request=request
            )
        if f"/{AD_ACCOUNT}/" in url:  # creare: campanie, set, creative, anunt
            return httpx.Response(200, json={"id": str(next(self._ids))}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)

    @property
    def capi(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["url"].endswith("/events")]


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> _FakeMeta:
    fake = _FakeMeta()
    sync_post, async_post = httpx.Client.post, httpx.AsyncClient.post

    def post(self: httpx.Client, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
        if "graph.facebook.com" in str(url):
            return fake.answer(str(url), dict(kwargs.get("data") or {}))
        return sync_post(self, url, *args, **kwargs)

    async def apost(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
        if "graph.facebook.com" in str(url):
            return fake.answer(str(url), dict(kwargs.get("data") or {}))
        return await async_post(self, url, *args, **kwargs)

    async def image(self: LiveMetaMarketingProvider, image_url: str) -> bytes:
        return b"\xff\xd8\xff\xe0" + b"0" * 2048  # un JPEG fictiv

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(httpx.AsyncClient, "post", apost)
    monkeypatch.setattr(LiveMetaMarketingProvider, "_download_image", image)
    return fake


@pytest.fixture
def pilot_env(agency_settings: Tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "PPC_PROVIDER_MODE": "live",
        "PPC_META_ACCESS_TOKEN": "TOKEN-FICTIV",
        "PPC_META_CURRENCY": "RON",
        "MAX_DAILY_SPEND_RON": "50",
        "META_CAPI_TEST_EVENT_CODE": TEST_CODE,
    }.items():
        monkeypatch.setenv(key, value)
    get_server_settings.cache_clear()


def test_pilotul_meta_simulat_cap_coada(
    client: TestClient,
    auth_headers: dict[str, str],
    session: Session,
    pilot_env: None,
    meta: _FakeMeta,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    # 1. Clientul fictiv se inscrie, agentia ii seteaza pixelul si contul de reclame.
    signup = client.post(
        "/api/v1/signup",
        json={
            "name": "Service Auto Demo SRL",
            "email": "pilot@demo-service.ro",
            "password": "parola-pilot-123",
        },
    )
    me = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    cid = int(client.get("/api/v1/me", headers=me).json()["account"]["id"])
    patched = client.patch(
        f"/api/v1/clients/{cid}",
        headers=auth_headers,
        json={"meta_pixel_id": PIXEL, "meta_ad_account_id": AD_ACCOUNT},
    )
    assert patched.status_code == 200, patched.text

    # 2. Comanda Gomag de test -> Conversions API, o singura data.
    order = {
        "id": 50001,
        "total": "349.90",
        "currency": "RON",
        "billing": {"email": "Ion.Popescu@Exemplu.ro", "phone": "0722 111 222"},
    }
    webhook = f"/api/v1/tracking/conversion/{cid}?source_platform=gomag"
    first = client.post(webhook, headers=auth_headers, json=order).json()
    assert (first["qualified"], first["meta_capi"]) == (True, "sent")
    [capi] = meta.capi
    assert capi["url"].endswith(f"/{PIXEL}/events")
    assert capi["data"]["test_event_code"] == TEST_CODE
    event = json.loads(capi["data"]["data"])[0]
    assert event["event_id"] == "gomag_order_50001"  # cheia de deduplicare cu pixelul
    assert event["event_name"] == "Purchase"
    assert event["custom_data"] == {"value": 349.9, "currency": "RON"}
    assert "popescu" not in json.dumps(event).lower()  # PII doar ca SHA-256

    # 3. Webhook-ul retrimis se deduplica; un apel scurt nu ajunge la Meta.
    again = client.post(webhook, headers=auth_headers, json=order).json()
    assert (again["deduplicated"], again["meta_capi"]) == (True, None)
    call = client.post(
        f"/api/v1/tracking/conversion/{cid}?source_platform=call_tracker",
        headers=auth_headers,
        json={"call_id": "c-9", "caller_id": "0733000000", "duration_seconds": 12},
    ).json()
    assert (call["qualified"], call["meta_capi"]) == (False, None)
    assert len(meta.capi) == 1

    def propose(
        op: ChangeOp, resource: str, kind: str, spend: str, after: dict[str, Any] | None = None
    ) -> int:
        change = ProposedChange(
            client_account_id=cid,
            op=op,
            resource=resource,
            resource_type=kind,
            projected_daily_spend=Decimal(spend),
            after=after or {},
            rationale="pilot simulat",
            source_module="e2e",
        )
        session.add(change)
        session.commit()
        session.refresh(change)
        return change.id or 0

    def approve(proposal_id: int) -> httpx.Response:
        return client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=me)

    # 4. In plafon: pauza, buget (in bani la Meta), lansare OPRITA. Total 45/50.
    assert approve(propose(ChangeOp.PAUSE, "meta_ad_set/6001", "ad_set", "0")).status_code == 200
    assert approve(propose(ChangeOp.UPDATE, "meta_ad_set/6002", "ad_set", "25")).status_code == 200
    assert meta.calls[-1]["data"]["daily_budget"] == "2500"
    before = len(meta.calls)
    launch = approve(
        propose(
            ChangeOp.CREATE_CAMPAIGN,
            f"meta_ad_account/{AD_ACCOUNT}",
            "ad_account",
            "20",
            _spec(daily_budget=Decimal("20")).to_payload(),
        )
    )
    assert launch.status_code == 200, launch.text
    statuses = {call["data"]["status"] for call in meta.calls[before:] if "status" in call["data"]}
    assert statuses == {"PAUSED"}  # nimic nu porneste fara un om, din Ads Manager

    # 5. Peste plafon (45 + 10 > 50): 409, nimic trimis, alerta CRITICAL; o pauza trece.
    before = len(meta.calls)
    over = propose(ChangeOp.UPDATE, "meta_ad_set/6003", "ad_set", "10")
    refused = approve(over)
    assert refused.status_code == 409
    assert len(meta.calls) == before
    stored = session.get(ProposedChange, over)
    assert stored is not None
    session.refresh(stored)
    assert stored.status is ChangeStatus.PENDING
    assert any(
        record.levelno == logging.CRITICAL
        and getattr(record, "event", None) == "spend_limit_exceeded"
        for record in caplog.records
    )
    pause = approve(propose(ChangeOp.PAUSE, "meta_campaign/7001", "campaign", "0"))
    assert pause.status_code == 200

    # 6. Un cont Meta in alta moneda decat plafonul (lei) nu se atinge.
    monkeypatch.setenv("PPC_META_CURRENCY", "EUR")
    euro = approve(propose(ChangeOp.UPDATE, "meta_ad_set/6004", "ad_set", "1"))
    assert euro.status_code == 409 and "EUR" in euro.json()["detail"]

    # In baza de date: doar hash-uri, niciun email in clar.
    for conversion in session.exec(select(ConversionEvent)).all():
        assert conversion.email_sha256 is None or len(conversion.email_sha256) == 64
