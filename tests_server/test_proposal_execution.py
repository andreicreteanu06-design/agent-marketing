"""Motorul de executie si endpoint-urile de aprobare/respingere.

Motorul se testeaza cu un provider dublu (Protocol ingust, fara retea);
endpoint-urile prin HTTP, cu ``httpx.AsyncClient.post`` inlocuit - niciun test
de aici nu are voie sa iasa in internet.

Doua invariante centrale:

1. O propunere ajunge ``EXECUTED`` doar daca platforma a confirmat.
2. Un termen de cautare Google Ads nu pleaca NICIODATA catre Graph API-ul Meta,
   oricat de disponibil ar fi providerul Meta.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.services.execution_engine import (
    NoExecutorError,
    ProposalNotExecutableError,
    execute_proposal,
    resolve_target,
)
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ProposedChange,
    Tenant,
)

#: Plafonul pentru testele motorului care nu sunt despre plafon: cel absolut, ca
#: sumele lor (ex. 120.50) sa treaca exact ca inainte.
_CAP = Decimal("500")


class _FakeMetaProvider:
    """Provider dublu: retine ce i s-a cerut, sau pica la comanda."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.paused_campaigns: list[str] = []
        self.paused_adsets: list[str] = []
        self.paused_ads: list[str] = []
        self.budgets: list[tuple[str, Decimal]] = []
        self._fail = fail

    def _maybe_fail(self) -> None:
        if self._fail:
            raise self._fail

    async def pause_campaign(self, campaign_id: str) -> None:
        self._maybe_fail()
        self.paused_campaigns.append(campaign_id)

    async def pause_adset(self, adset_id: str) -> None:
        self._maybe_fail()
        self.paused_adsets.append(adset_id)

    async def pause_ad(self, ad_id: str) -> None:
        self._maybe_fail()
        self.paused_ads.append(ad_id)

    async def update_budget(self, object_id: str, new_daily_budget: Decimal) -> None:
        self._maybe_fail()
        self.budgets.append((object_id, new_daily_budget))

    @property
    def touched(self) -> bool:
        """Adevarat daca providerul a fost chemat in vreun fel."""
        return bool(
            self.paused_campaigns or self.paused_adsets or self.paused_ads or self.budgets
        )


def _proposal(
    client_account_id: int = 1,
    *,
    op: ChangeOp = ChangeOp.PAUSE,
    resource: str = "meta_ad_set/23848",
    resource_type: str = "ad_set",
    spend: str = "0",
) -> ProposedChange:
    return ProposedChange(
        client_account_id=client_account_id,
        op=op,
        resource=resource,
        resource_type=resource_type,
        projected_daily_spend=Decimal(spend),
        rationale="test",
        source_module="test",
    )


# --- rezolvarea resursei ----------------------------------------------------


@pytest.mark.parametrize(
    ("resource", "resource_type", "platform", "kind", "object_id"),
    [
        ("meta_ad_set/23848", "ad_set", "meta", "ad_set", "23848"),
        ("meta_campaign/120", "campaign", "meta", "campaign", "120"),
        ("meta_ad/7", "ad", "meta", "ad", "7"),
        ("campaign/555", "campaign", "google_ads", "campaign", "555"),
        ("tiktok_ad_group/9", "ad_group", "tiktok", "ad_group", "9"),
        ("service auto", "ppc_keyword", "google_ads", "keyword", "service auto"),
        ("reparatii", "keyword_budget", "google_ads", "keyword", "reparatii"),
    ],
)
def test_resursa_isi_declara_platforma_si_id_ul(
    resource: str, resource_type: str, platform: str, kind: str, object_id: str
) -> None:
    target = resolve_target(_proposal(resource=resource, resource_type=resource_type))
    assert (target.platform, target.kind, target.object_id) == (platform, kind, object_id)


def test_consolidarea_de_lichiditate_nu_e_un_obiect_real() -> None:
    """``ad_set_group/`` are id sintetizat de noi - nu exista in contul Meta."""
    proposal = _proposal(resource="ad_set_group/as_1+as_2", resource_type="ad_set")
    with pytest.raises(NoExecutorError, match="consolidare"):
        resolve_target(proposal)


# --- motorul ----------------------------------------------------------------


def test_pauza_pe_set_de_reclame_ajunge_la_provider_fara_prefix() -> None:
    provider = _FakeMetaProvider()
    result = execute_proposal(_proposal(), provider, current_status="pending", max_daily_spend=_CAP)
    assert result.executed is True
    assert provider.paused_adsets == ["23848"]


def test_pauza_pe_campanie_si_pe_anunt_merg_pe_metode_diferite() -> None:
    campaign = _FakeMetaProvider()
    execute_proposal(
        _proposal(resource="meta_campaign/120", resource_type="campaign"),
        campaign,
        current_status="pending",
        max_daily_spend=_CAP,
    )
    assert campaign.paused_campaigns == ["120"]

    ad = _FakeMetaProvider()
    execute_proposal(
        _proposal(resource="meta_ad/7", resource_type="ad"),
        ad,
        current_status="pending",
        max_daily_spend=_CAP,
    )
    assert ad.paused_ads == ["7"]


def test_actualizarea_de_buget_trimite_suma() -> None:
    provider = _FakeMetaProvider()
    proposal = _proposal(op=ChangeOp.UPDATE, spend="120.50")
    execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.budgets == [("23848", Decimal("120.50"))]


def test_un_anunt_nu_are_buget_propriu() -> None:
    """La Meta bugetul sta pe set sau pe campanie, nu pe anunt."""
    provider = _FakeMetaProvider()
    proposal = _proposal(op=ChangeOp.UPDATE, resource="meta_ad/7", resource_type="ad")
    with pytest.raises(NoExecutorError, match="UPDATE"):
        execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.touched is False


def test_o_propunere_ne_pending_nu_se_re_executa() -> None:
    """Un dublu-click pe aprobare nu trebuie sa dubleze o schimbare de buget."""
    with pytest.raises(ProposalNotExecutableError):
        execute_proposal(
            _proposal(), _FakeMetaProvider(), current_status="executed", max_daily_spend=_CAP
        )


def test_un_termen_google_ads_nu_pleaca_niciodata_spre_meta() -> None:
    """Invariantul cel mai important din modul.

    Propunerile motorului hibrid poarta un TERMEN DE CAUTARE, nu un id de obiect.
    Trimis la Graph API, "service auto" ar fi un id strain sau invalid - deci se
    opreste inainte de orice apel, chiar daca providerul Meta e la indemana.
    """
    provider = _FakeMetaProvider()
    proposal = _proposal(resource="service auto", resource_type="ppc_keyword")
    with pytest.raises(NoExecutorError, match="google_ads"):
        execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.touched is False


def test_tip_fara_executor_nu_se_aplica_pe_aproape() -> None:
    proposal = _proposal(resource="ceva", resource_type="widget_necunoscut")
    with pytest.raises(NoExecutorError, match="widget_necunoscut"):
        execute_proposal(
            proposal, _FakeMetaProvider(), current_status="pending", max_daily_spend=_CAP
        )


def test_esecul_platformei_devine_rezultat_nu_exceptie() -> None:
    """Propunerea trebuie marcata FAILED cu motiv, nu sa arunce in sus."""
    provider = _FakeMetaProvider(fail=RuntimeError("token expirat"))
    result = execute_proposal(_proposal(), provider, current_status="pending", max_daily_spend=_CAP)
    assert result.executed is False
    assert "token expirat" in result.error


# --- endpoint-urile ---------------------------------------------------------


def _signup(client: TestClient) -> tuple[dict[str, str], int]:
    response = client.post(
        "/api/v1/signup",
        json={"name": "Client HITL", "email": "hitl@exemplu.ro", "password": "parola-sigura-123"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = client.get("/api/v1/me", headers=headers).json()["account"]["id"]
    return headers, int(account_id)


@pytest.fixture
def hitl(
    client: TestClient, agency_settings: Tenant, session: Session
) -> tuple[TestClient, dict[str, str], int]:
    headers, account_id = _signup(client)
    return client, headers, account_id


@pytest.fixture
def meta_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server in mod live, cu un token Meta - fara asta aprobarea da 409.

    Nu iese in retea: cererea reala e interceptata de fixture-ul ``graph_api``.
    """
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "token-de-test")
    monkeypatch.setenv("PPC_META_CURRENCY", "RON")


class _GraphApiStub:
    """``httpx.AsyncClient.post`` inlocuit: retine apelurile, raspunde la comanda.

    Implicit raspunde 200 ``{"success": true}``, ca la o schimbare acceptata de
    Meta; ``enqueue`` pune la coada un raspuns pentru urmatorul apel.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._queued: list[httpx.Response] = []

    def enqueue(self, response: httpx.Response) -> None:
        self._queued.append(response)

    def record(self, url: str, data: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        self.calls.append({"url": url, "data": data, "headers": headers})
        if self._queued:
            return self._queued.pop(0)
        return httpx.Response(200, json={"success": True}, request=httpx.Request("POST", url))


@pytest.fixture
def graph_api(monkeypatch: pytest.MonkeyPatch) -> _GraphApiStub:
    """Nicio cerere reala catre graph.facebook.com din testele astea."""
    stub = _GraphApiStub()

    async def fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        return stub.record(str(url), dict(data or {}), dict(headers or {}))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return stub


def _add_pending(
    session: Session,
    account_id: int,
    *,
    op: ChangeOp = ChangeOp.PAUSE,
    resource: str = "meta_ad_set/23848",
    resource_type: str = "ad_set",
    spend: str = "0",
) -> int:
    change = _proposal(
        account_id, op=op, resource=resource, resource_type=resource_type, spend=spend
    )
    session.add(change)
    session.commit()
    session.refresh(change)
    return change.id or 0


def test_pending_listeaza_doar_propunerile_clientului(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hitl
    _add_pending(session, account_id)
    _add_pending(session, account_id + 999)

    rows = client.get("/api/v1/proposals/pending", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["resource"] == "meta_ad_set/23848"


def test_pending_cere_autentificare(client: TestClient) -> None:
    assert client.get("/api/v1/proposals/pending").status_code == 401


def test_respingerea_nu_atinge_nicio_platforma(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    response = client.post(f"/api/v1/proposals/{proposal_id}/reject", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == ChangeStatus.REJECTED.value

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.REJECTED
    assert change.decided_by == "hitl@exemplu.ro"


def test_nu_se_respinge_de_doua_ori(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    client.post(f"/api/v1/proposals/{proposal_id}/reject", headers=headers)
    second = client.post(f"/api/v1/proposals/{proposal_id}/reject", headers=headers)
    assert second.status_code == 409


def test_propunerea_altui_client_da_404(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    """Acelasi raspuns pentru "nu exista" si "nu e a ta" - un id ghicit nu confirma nimic."""
    client, headers, account_id = hitl
    foreign = _add_pending(session, account_id + 999)
    assert client.post(f"/api/v1/proposals/{foreign}/reject", headers=headers).status_code == 404


# --- aprobarea, pana la Graph API -------------------------------------------


def test_aprobarea_pune_pe_pauza_setul_de_reclame_in_meta(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == ChangeStatus.EXECUTED.value

    (call,) = graph_api.calls
    assert call["url"] == "https://graph.facebook.com/v25.0/23848"
    assert call["data"] == {"status": "PAUSED"}
    assert call["headers"]["Authorization"] == "Bearer token-de-test"

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.EXECUTED
    assert change.error_message is None
    assert change.decided_by == "hitl@exemplu.ro"


def test_bugetul_pleaca_in_bani_nu_in_lei(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """Graph API primeste unitatea minima a monedei: 25.50 RON -> 2550."""
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="25.50")

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 200

    (call,) = graph_api.calls
    assert call["data"] == {"daily_budget": "2550"}


def test_un_refuz_de_la_meta_lasa_propunerea_failed_cu_motivul_ei(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """502 si FAILED - platforma a fost intrebata si a spus nu."""
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    graph_api.enqueue(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "type": "OAuthException",
                    "code": 100,
                    "error_user_msg": "Ad set nu mai exista.",
                }
            },
            request=httpx.Request("POST", "https://graph.facebook.com/v25.0/23848"),
        )
    )

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 502

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.FAILED
    assert change.error_message is not None
    assert "Invalid parameter" in change.error_message


def test_un_token_expirat_e_semnalat_ca_problema_de_configurare(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    graph_api.enqueue(
        httpx.Response(
            401,
            json={"error": {"message": "Session has expired", "code": 190}},
            request=httpx.Request("POST", "https://graph.facebook.com/v25.0/23848"),
        )
    )

    assert (
        client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers).status_code
        == 502
    )
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.error_message is not None
    assert "reconecteaza contul" in change.error_message


def test_un_termen_google_ads_nu_ajunge_la_graph_api_nici_prin_endpoint(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """Propunerile evaluatorului de noapte: 409, PENDING, zero apeluri."""
    client, headers, account_id = hitl
    proposal_id = _add_pending(
        session, account_id, resource="service auto", resource_type="ppc_keyword"
    )

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 409
    assert graph_api.calls == []

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_modul_mock_nu_se_preface_ca_a_aplicat(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    graph_api: _GraphApiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fara mod live, aprobarea da 409 si propunerea ramane in asteptare."""
    monkeypatch.setenv("PPC_PROVIDER_MODE", "mock")
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 409
    assert "mock" in response.json()["detail"]
    assert graph_api.calls == []

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_contul_meta_neconectat_da_409_nu_500(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    graph_api: _GraphApiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "")
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 409
    assert "nu e conectat" in response.json()["detail"]
    assert graph_api.calls == []


def test_o_propunere_deja_decisa_nu_se_mai_aproba(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    change.status = ChangeStatus.EXECUTED
    change.decided_at = datetime.now(tz=UTC)
    session.add(change)
    session.commit()

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 409
    assert graph_api.calls == []
    assert (
        session.exec(
            select(ProposedChange).where(ProposedChange.id == proposal_id)
        ).one().status
        is ChangeStatus.EXECUTED
    )


def test_plafonul_de_cheltuiala_opreste_aprobarea_inainte_de_orice_apel(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """Plafonul implicit e 50 RON/zi; o propunere de 500 nu trebuie sa plece."""
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="500")

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 409
    assert graph_api.calls == []


def test_asyncio_run_nu_ramane_cu_bucla_pornita() -> None:
    """Puntea sincrona trebuie sa poata fi apelata de mai multe ori la rand."""
    provider = _FakeMetaProvider()
    for _ in range(3):
        execute_proposal(_proposal(), provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.paused_adsets == ["23848"] * 3
    assert asyncio.get_event_loop_policy() is not None


# --- rezervarea atomica (dublu click, aprobari simultane) ----------------------


def _slow_graph_api(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], Any, Any]:
    """Graph API care tine prima cerere "in zbor" pana cand testul o elibereaza."""
    import threading

    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    async def slow_post(
        self: httpx.AsyncClient, url: str, *, data: Any = None, headers: Any = None, **kw: Any
    ) -> httpx.Response:
        calls.append(str(url))
        entered.set()
        release.wait(timeout=10)
        return httpx.Response(200, json={"success": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
    return calls, entered, release


def _in_background(
    client: TestClient, url: str, headers: dict[str, str]
) -> tuple[Any, dict[str, Any]]:
    import threading

    box: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: box.update(response=client.post(url, headers=headers)))
    thread.start()
    return thread, box


def test_dublu_click_pe_aprobare_aplica_o_singura_data(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    calls, entered, release = _slow_graph_api(monkeypatch)
    url = f"/api/v1/proposals/{proposal_id}/approve"

    thread, first = _in_background(client, url, headers)
    assert entered.wait(timeout=10)  # prima cerere a rezervat si e in zbor spre Meta
    second = client.post(url, headers=headers)
    release.set()
    thread.join(timeout=10)

    assert second.status_code == 409
    assert first["response"].status_code == 200
    assert first["response"].json()["status"] == ChangeStatus.EXECUTED.value
    assert len(calls) == 1  # un singur apel catre Meta


def test_rezervarea_e_atomica_chiar_daca_ambele_cereri_au_citit_pending(
    engine: Any, session: Session
) -> None:
    """Cursa adevarata: ambele cereri au vazut PENDING; UPDATE-ul conditionat alege una."""
    from ppc_agent_server.routers.proposals import _transition

    proposal_id = _add_pending(session, 1)
    with Session(engine) as first, Session(engine) as second:
        mine = first.get(ProposedChange, proposal_id)
        theirs = second.get(ProposedChange, proposal_id)
        assert mine is not None and theirs is not None
        assert mine.status is theirs.status is ChangeStatus.PENDING

        assert _transition(first, mine, frm=ChangeStatus.PENDING, to=ChangeStatus.APPROVED)
        assert not _transition(second, theirs, frm=ChangeStatus.PENDING, to=ChangeStatus.APPROVED)
        assert theirs.status is ChangeStatus.APPROVED  # vede starea reala, nu pe a ei


def test_plafonul_numara_si_propunerile_aflate_in_curs_de_aplicare(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plafon 50 RON: doua propuneri de 30 aprobate deodata nu trec amandoua."""
    client, headers, account_id = hitl
    first_id = _add_pending(session, account_id, spend="30")
    second_id = _add_pending(session, account_id, resource="meta_ad_set/777", spend="30")
    calls, entered, release = _slow_graph_api(monkeypatch)

    thread, first = _in_background(client, f"/api/v1/proposals/{first_id}/approve", headers)
    assert entered.wait(timeout=10)
    second = client.post(f"/api/v1/proposals/{second_id}/approve", headers=headers)
    release.set()
    thread.join(timeout=10)

    assert first["response"].status_code == 200
    assert second.status_code == 409  # 30 in zbor + 30 > 50
    assert len(calls) == 1
    change = session.get(ProposedChange, second_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_o_rezervare_refuzata_dupa_preluare_se_elibereaza(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plafonul re-verificat DUPA rezervare pica -> propunerea revine PENDING, nimic trimis."""
    from ppc_agent.errors import SpendLimitExceeded
    from ppc_agent_server.routers import proposals as proposals_router

    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)
    checks: list[int | None] = []

    def flaky_check(*args: Any, exclude_id: int | None = None, **kwargs: Any) -> None:
        checks.append(exclude_id)
        if exclude_id is not None:  # a doua verificare, dupa rezervare
            raise SpendLimitExceeded("alta aprobare a luat plafonul intre timp")

    monkeypatch.setattr(proposals_router, "check_spend_limit", flaky_check)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert checks == [None, proposal_id]
    assert graph_api.calls == []
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_o_executie_intrerupta_nu_ramane_rezervata_la_nesfarsit(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nu stim daca Meta a aplicat: FAILED (verificare manuala), nu PENDING (reincercare oarba)."""
    from ppc_agent_server.routers import proposals as proposals_router

    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    def crash(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("conexiune pierduta la mijlocul cererii")

    monkeypatch.setattr(proposals_router, "run_execution", crash)

    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.FAILED
    assert change.error_message is not None
    assert "verifica in platforma" in change.error_message
