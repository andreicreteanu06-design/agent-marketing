"""Secventa de lansare Meta: ordinea apelurilor, rollback-ul si aprobarea.

Nicio cerere reala. La nivel de provider: httpx.MockTransport, cu DNS-ul
validarii anti-SSRF raspuns de noi. La nivel de endpoint: httpx.AsyncClient.post
si .delete inlocuite, descarcarea imaginii inlocuita cu octeti falsi, iar
AsyncClient.send blocat - orice cerere scapata printre ele pica testul.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.errors import CampaignLaunchError
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.meta_campaign import MetaLaunchSpec
from ppc_agent_server.models import ChangeStatus, ClientAccount, ProposedChange, Tenant
from seo_geo_agent.audit import url_policy

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
_IDS: dict[str, dict[str, Any]] = {
    "/campaigns": {"id": "camp_123"},
    "/adsets": {"id": "adset_456"},
    "/adimages": {"images": {"bytes": {"hash": "hash_abc"}}},
    "/adcreatives": {"id": "creative_321"},
    "/ads": {"id": "ad_789"},
}
_META_REFUSAL = {
    "error": {
        "message": "Invalid parameter",
        "code": 100,
        "error_user_msg": "Bugetul zilnic e sub minimul permis.",
    }
}


def _spec(**overrides: Any) -> MetaLaunchSpec:
    fields: dict[str, Any] = {
        "campaign_name": "Service Auto - Vanzari",
        "objective": CampaignObjective.SALES,
        "daily_budget": Decimal("25.00"),
        "pixel_id": "1234567890",
        "custom_event_type": "PURCHASE",
        "page_id": "9876543210",
        "target_url": "https://exemplu.ro/oferta",
        "headline": "Revizie completa in 24h",
        "primary_text": "Programeaza revizia online.",
        "image_url": "https://cdn.exemplu.ro/reclama.jpg",
        "country": "RO",
        "call_to_action": "SHOP_NOW",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validarea anti-SSRF rezolva DNS - in teste raspundem noi, nu reteaua."""

    async def public(hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", public)


# --- providerul: secventa si rollback-ul -----------------------------------


class _Meta:
    """Graph API + serverul imaginii, simulate prin MockTransport."""

    def __init__(
        self,
        *,
        fail_on: str | None = None,
        timeout_on: str | None = None,
        delete_fails: bool = False,
        image: httpx.Response | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self._fail_on = fail_on
        self._timeout_on = timeout_on
        self._delete_fails = delete_fails
        self._image = image

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = dict(parse_qsl(request.content.decode())) if request.method == "POST" else {}
        self.calls.append((request.method, url, body))
        if request.method == "GET":
            return self._image or httpx.Response(
                200, content=_PNG, headers={"content-type": "image/png"}
            )
        if request.method == "DELETE":
            if self._delete_fails:
                return httpx.Response(500, json={"error": {"message": "Service unavailable"}})
            return httpx.Response(200, json={"success": True})
        for suffix, payload in _IDS.items():
            if url.endswith(suffix):
                if self._timeout_on == suffix:
                    raise httpx.ReadTimeout("fara raspuns", request=request)
                if self._fail_on == suffix:
                    return httpx.Response(400, json=_META_REFUSAL)
                return httpx.Response(200, json=payload)
        raise AssertionError(f"cerere neasteptata: {request.method} {url}")

    def provider(self, currency: str = "RON") -> LiveMetaMarketingProvider:
        return LiveMetaMarketingProvider(
            access_token="token-123",
            currency=currency,
            transport=httpx.MockTransport(self.handler),
        )

    def launch(self, spec: MetaLaunchSpec | None = None, currency: str = "RON") -> Any:
        return asyncio.run(self.provider(currency).launch_campaign("act_555", spec or _spec()))

    @property
    def meta_posts(self) -> list[str]:
        return [url.rsplit("/", 1)[-1] for method, url, _ in self.calls if method == "POST"]

    @property
    def deleted(self) -> list[str]:
        return [url.rsplit("/", 1)[-1] for method, url, _ in self.calls if method == "DELETE"]

    def body_of(self, edge: str) -> dict[str, str]:
        for method, url, body in self.calls:
            if method == "POST" and url.endswith(f"/{edge}"):
                return body
        raise AssertionError(f"niciun POST pe /{edge}")


def test_secventa_creeaza_totul_oprit_in_ordinea_corecta() -> None:
    meta = _Meta()
    result = meta.launch()

    assert result.as_dict() == {
        "campaign_id": "camp_123",
        "adset_id": "adset_456",
        "image_hash": "hash_abc",
        "creative_id": "creative_321",
        "ad_id": "ad_789",
    }
    assert meta.calls[0][0] == "GET"  # imaginea, INAINTE de orice apel Meta
    assert meta.meta_posts == ["campaigns", "adsets", "adimages", "adcreatives", "ads"]
    for edge in ("campaigns", "adsets", "ads"):
        assert meta.body_of(edge)["status"] == "PAUSED"
    assert meta.deleted == []


def test_campurile_obligatorii_v24_v25_ajung_la_meta() -> None:
    meta = _Meta()
    meta.launch()

    campaign = meta.body_of("campaigns")
    assert campaign["is_adset_budget_sharing_enabled"] == "false"
    assert campaign["special_ad_categories"] == "[]"
    adset = meta.body_of("adsets")
    assert adset["campaign_id"] == "camp_123"
    assert json.loads(adset["targeting"])["targeting_automation"] == {"advantage_audience": 1}
    story = json.loads(meta.body_of("adcreatives")["object_story_spec"])
    assert story["link_data"]["image_hash"] == "hash_abc"
    assert json.loads(meta.body_of("ads")["creative"]) == {"creative_id": "creative_321"}
    assert meta.body_of("ads")["adset_id"] == "adset_456"


def test_bugetul_se_converteste_in_bani_abia_la_trimitere() -> None:
    ron = _Meta()
    ron.launch(_spec(daily_budget=Decimal("25.00")))
    assert ron.body_of("adsets")["daily_budget"] == "2500"

    huf = _Meta()
    huf.launch(_spec(daily_budget=Decimal("2500")), currency="HUF")
    assert huf.body_of("adsets")["daily_budget"] == "2500"  # fara subunitate: x1


@pytest.mark.parametrize(
    ("fail_on", "stage"),
    [
        ("/adsets", "adset"),
        ("/adimages", "image_upload"),
        ("/adcreatives", "creative"),
        ("/ads", "ad"),
    ],
)
def test_orice_pas_picat_dupa_campanie_o_sterge(fail_on: str, stage: str) -> None:
    meta = _Meta(fail_on=fail_on)
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch()

    error = caught.value
    assert error.stage == stage
    assert error.rolled_back is True
    assert error.campaign_id == "camp_123"
    assert meta.deleted == ["camp_123"]
    assert "Invalid parameter" in str(error)
    assert "Bugetul zilnic e sub minimul permis." in str(error)
    assert "stearsa (rollback)" in str(error)


def test_daca_pica_chiar_campania_nu_e_nimic_de_sters() -> None:
    meta = _Meta(fail_on="/campaigns")
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch()
    assert caught.value.stage == "campaign"
    assert meta.meta_posts == ["campaigns"]
    assert meta.deleted == []
    assert "Nimic nu a fost creat" in str(caught.value)


def test_un_timeout_la_creare_nu_pretinde_ca_nu_s_a_creat_nimic() -> None:
    """Meta poate crea campania si pierde raspunsul - nu stim, si o spunem."""
    meta = _Meta(timeout_on="/campaigns")
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch()
    assert "NECUNOSCUT" in str(caught.value)
    assert "Nimic nu a fost creat" not in str(caught.value)


def test_un_rollback_esuat_e_raportat_cu_id_ul_campaniei() -> None:
    meta = _Meta(fail_on="/adsets", delete_fails=True)
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch()
    assert caught.value.rolled_back is False
    assert caught.value.campaign_id == "camp_123"
    assert "ATENTIE" in str(caught.value)
    assert "camp_123" in str(caught.value)


@pytest.mark.parametrize(
    "image_url",
    [
        "https://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/x.png",
        "https://localhost/x.png",
    ],
)
def test_o_imagine_de_la_o_adresa_interna_nu_e_ceruta_deloc(image_url: str) -> None:
    meta = _Meta()
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch(_spec(image_url=image_url))
    assert caught.value.stage == "image_download"
    assert meta.calls == []  # nici imaginea, nici Meta


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (
            httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"}),
            "nu e o imagine",
        ),
        (httpx.Response(302, headers={"location": "http://10.0.0.1/x.png"}), "redirectioneaza"),
        (httpx.Response(404), "404"),
    ],
)
def test_o_imagine_proasta_opreste_totul_inainte_de_meta(
    image: httpx.Response, message: str
) -> None:
    meta = _Meta(image=image)
    with pytest.raises(CampaignLaunchError, match=message) as caught:
        meta.launch()
    assert caught.value.stage == "image_download"
    assert meta.meta_posts == []


def test_url_ul_semnat_al_imaginii_se_cere_exact_cum_a_fost_dat() -> None:
    """Forma normalizata ar sorta parametrii si ar strica semnatura CDN-ului."""
    signed = "https://cdn.exemplu.ro/img.jpg?X-Signature=abc&A-Expires=1"
    meta = _Meta()
    meta.launch(_spec(image_url=signed))
    assert meta.calls[0][1] == signed


# --- aprobarea, prin endpoint ----------------------------------------------


class _Graph:
    """Ce raspund AsyncClient.post/delete inlocuite."""

    def __init__(self) -> None:
        self.fail_on: str | None = None
        self.delete_fails = False
        self.posts: list[str] = []
        self.deleted: list[str] = []

    def post(self, url: str) -> httpx.Response:
        self.posts.append(url)
        request = httpx.Request("POST", url)
        for suffix, payload in _IDS.items():
            if url.endswith(suffix):
                if self.fail_on == suffix:
                    return httpx.Response(400, json=_META_REFUSAL, request=request)
                return httpx.Response(200, json=payload, request=request)
        raise AssertionError(f"POST neasteptat: {url}")

    def delete(self, url: str) -> httpx.Response:
        self.deleted.append(url.rsplit("/", 1)[-1])
        request = httpx.Request("DELETE", url)
        if self.delete_fails:
            return httpx.Response(500, json={"error": {"message": "down"}}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> _Graph:
    stub = _Graph()

    async def fake_post(self: httpx.AsyncClient, url: Any, **kwargs: Any) -> httpx.Response:
        return stub.post(str(url))

    async def fake_delete(self: httpx.AsyncClient, url: Any, **kwargs: Any) -> httpx.Response:
        return stub.delete(str(url))

    async def no_send(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> Any:
        raise AssertionError(f"cerere reala blocata: {request.method} {request.url}")

    async def fake_image(self: LiveMetaMarketingProvider, image_url: str) -> bytes:
        return _PNG

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "delete", fake_delete)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_send)
    monkeypatch.setattr(LiveMetaMarketingProvider, "_download_image", fake_image)
    return stub


_REQUEST: dict[str, Any] = {
    "campaign_name": "Service Auto - Vanzari",
    "daily_budget": "25.00",
    "pixel_id": "1234567890",
    "page_id": "9876543210",
    "target_url": "https://exemplu.ro/oferta",
    "headline": "Revizie completa in 24h",
    "primary_text": "Programeaza revizia online.",
    "image_url": "https://cdn.exemplu.ro/reclama.jpg",
}


def _account(client: TestClient, session: Session) -> dict[str, str]:
    response = client.post(
        "/api/v1/signup",
        json={
            "name": "Client Lansare",
            "email": "lansare@exemplu.ro",
            "password": "parola-sigura-123",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    account_id = client.get("/api/v1/me", headers=headers).json()["account"]["id"]
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.meta_ad_account_id = "act_555"
    session.add(account)
    session.commit()
    return headers


def _propose(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_REQUEST)
    assert response.status_code == 201
    return int(response.json()["id"])


def _approve(client: TestClient, headers: dict[str, str], proposal_id: int) -> httpx.Response:
    return client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)


@pytest.fixture
def live(
    client: TestClient,
    agency_settings: Tenant,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, dict[str, str]]:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "token-de-test")
    monkeypatch.setenv("PPC_META_CURRENCY", "RON")
    return client, _account(client, session)


def _stored(session: Session, proposal_id: int) -> ProposedChange:
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    return change


def test_aprobarea_lanseaza_campania_si_pastreaza_id_urile(
    live: tuple[TestClient, dict[str, str]], session: Session, graph: _Graph
) -> None:
    client, headers = live
    proposal_id = _propose(client, headers)
    assert graph.posts == []  # propunerea singura nu atinge Meta

    response = _approve(client, headers, proposal_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ChangeStatus.EXECUTED.value
    assert body["execution_result"] == {
        "campaign_id": "camp_123",
        "adset_id": "adset_456",
        "image_hash": "hash_abc",
        "creative_id": "creative_321",
        "ad_id": "ad_789",
    }
    assert [url.rsplit("/", 1)[-1] for url in graph.posts] == [
        "campaigns",
        "adsets",
        "adimages",
        "adcreatives",
        "ads",
    ]
    assert all(url.startswith("https://graph.facebook.com/v25.0/act_555/") for url in graph.posts)
    assert graph.deleted == []


def test_un_refuz_meta_la_ad_set_sterge_campania_si_marcheaza_failed(
    live: tuple[TestClient, dict[str, str]], session: Session, graph: _Graph
) -> None:
    client, headers = live
    graph.fail_on = "/adsets"
    proposal_id = _propose(client, headers)

    response = _approve(client, headers, proposal_id)

    assert response.status_code == 502
    assert graph.deleted == ["camp_123"]
    change = _stored(session, proposal_id)
    assert change.status is ChangeStatus.FAILED
    assert change.error_message is not None
    assert "adset" in change.error_message
    assert "Invalid parameter" in change.error_message
    assert "stearsa (rollback)" in change.error_message
    assert change.execution_result is None


def test_campania_ramasa_dupa_un_rollback_esuat_apare_in_date(
    live: tuple[TestClient, dict[str, str]], session: Session, graph: _Graph
) -> None:
    client, headers = live
    graph.fail_on = "/adsets"
    graph.delete_fails = True
    proposal_id = _propose(client, headers)

    response = _approve(client, headers, proposal_id)

    assert response.status_code == 502
    change = _stored(session, proposal_id)
    assert change.execution_result == {"orphan_campaign_id": "camp_123"}
    assert change.error_message is not None
    assert "ATENTIE" in change.error_message


def test_un_dublu_click_nu_lanseaza_a_doua_campanie(
    live: tuple[TestClient, dict[str, str]], session: Session, graph: _Graph
) -> None:
    client, headers = live
    proposal_id = _propose(client, headers)
    _approve(client, headers, proposal_id)

    second = _approve(client, headers, proposal_id)

    assert second.status_code == 409
    assert len(graph.posts) == 5


def test_in_modul_mock_lansarea_nu_pleaca_nicaieri(
    client: TestClient,
    agency_settings: Tenant,
    session: Session,
    graph: _Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "mock")
    headers = _account(client, session)
    proposal_id = _propose(client, headers)

    response = _approve(client, headers, proposal_id)

    assert response.status_code == 409
    assert graph.posts == []
    assert graph.deleted == []
    assert _stored(session, proposal_id).status is ChangeStatus.PENDING
