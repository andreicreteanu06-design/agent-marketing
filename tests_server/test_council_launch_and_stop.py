"""Nicio lansare fara consiliu si oprirea de urgenta a adminului, din chat.

Consiliul de lansare e dublat (raspuns instant, fara surse live); restrictiile vin din
memoria lui reala (``MemoryStream``), ca in tura de noapte.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.config import ProviderMode
from ppc_agent_server.jobs.tasks import run_propose_job
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    EmergencyStop,
    MemoryStream,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.routers import queen
from ppc_agent_server.routers.campaigns import get_launch_council
from ppc_agent_server.services import emergency_stop
from ppc_agent_server.services.council import CouncilReply
from ppc_agent_server.settings import get_server_settings
from tests_server.test_campaign_launch import ready_to_launch

ADMIN = "andreicreteanu06@gmail.com"
LAUNCH = {
    "campaign_name": "Service Auto - Vanzari",
    "daily_budget": "25.00",
    "pixel_id": "1234567890",
    "page_id": "9876543210",
    "target_url": "https://exemplu.ro/oferta",
    "headline": "Revizie completa in 24h",
    "primary_text": "Programeaza revizia online.",
    "image_url": "https://cdn.exemplu.ro/reclama.jpg",
}


@pytest.fixture
def admins(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ADMIN_EMAILS", f" {ADMIN.upper()} , altcineva@exemplu.ro")
    get_server_settings.cache_clear()
    yield
    get_server_settings.cache_clear()


class _Council:
    """Consiliul de lansare, dublat: tine minte intrebarile."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.questions: list[str] = []
        self.error = error

    def __call__(self, session: Session, client_account_id: int, question: str) -> CouncilReply:
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        return queen._command_reply(client_account_id, "Testul merge, în plafon.")


def _login(client: TestClient, session: Session, email: str) -> tuple[dict[str, str], int]:
    response = client.post(
        "/api/v1/signup",
        json={"name": "Client", "email": email, "password": "parola-sigura-123"},
    )
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    account_id = int(client.get("/api/v1/me", headers=headers).json()["account"]["id"])
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.meta_ad_account_id = "act_555"
    ready_to_launch(account)
    session.add(account)
    session.commit()
    return headers, account_id


@pytest.fixture
def council(client: TestClient) -> _Council:
    fake = _Council()
    client.app.dependency_overrides[get_launch_council] = lambda: fake  # type: ignore[attr-defined]
    return fake


def _veto(session: Session, account_id: int) -> None:
    session.add(MemoryStream(
        client_account_id=account_id, timestamp=datetime.now(tz=UTC), agent_role="cto",
        topic="budget", decision="a pus veto: tracking-ul e picat pe Pixelul Meta",
        observation="", code="ATTRIBUTION_BROKEN",
    ))
    session.commit()


def _propose(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post("/api/v1/campaigns/propose_launch", headers=headers, json=LAUNCH)


# --- consiliul inainte de lansare ------------------------------------------------------


def test_lansarea_trece_prin_consiliu_si_poarta_avizul(
    client: TestClient, session: Session, agency_settings: Tenant, council: _Council
) -> None:
    headers, _ = _login(client, session, "client@exemplu.ro")
    response = _propose(client, headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    question = council.questions[0]
    assert "«Service Auto - Vanzari»" in question and "25.00 RON" in question
    assert body["before"]["council_review"]["decision"] == "Testul merge, în plafon."
    assert "Consiliul: Testul merge, în plafon. CCO:" in body["rationale"]


def test_fara_consiliu_nu_se_lanseaza_nimic(
    client: TestClient, session: Session, agency_settings: Tenant
) -> None:
    client.app.dependency_overrides[get_launch_council] = (  # type: ignore[attr-defined]
        lambda: _Council(error=RuntimeError("sursele au picat"))
    )
    headers, account_id = _login(client, session, "client@exemplu.ro")

    response = _propose(client, headers)

    assert response.status_code == 503
    assert session.exec(
        select(ProposedChange).where(ProposedChange.client_account_id == account_id)
    ).all() == []


def test_un_veto_al_tehnicianului_scrie_lansarea_blocata(
    client: TestClient, session: Session, agency_settings: Tenant, council: _Council
) -> None:
    headers, account_id = _login(client, session, "client@exemplu.ro")
    _veto(session, account_id)

    body = _propose(client, headers).json()

    assert body["status"] == "blocked"
    assert body["error_message"].startswith("Oprită de consiliu.")
    assert body["before"]["council"]["code"] == "ATTRIBUTION_BROKEN"
    assert "council_review" in body["before"]  # avizul ramane, ca sa se vada de ce


def test_aprobarea_unei_lansari_fara_aviz_sau_cu_veto_nou_e_refuzata(
    client: TestClient, session: Session, agency_settings: Tenant, council: _Council
) -> None:
    headers, account_id = _login(client, session, "client@exemplu.ro")
    old = ProposedChange(
        client_account_id=account_id, op=ChangeOp.CREATE_CAMPAIGN,
        resource="meta_ad_account/act_555", resource_type="campaign", before={}, after={},
        projected_daily_spend=Decimal("25"), rationale="lansare veche",
        source_module="campaign_launch", status=ChangeStatus.PENDING,
    )
    session.add(old)
    session.commit()
    response = client.post(f"/api/v1/proposals/{old.id}/approve", headers=headers)
    assert response.status_code == 409 and "n-a trecut prin consiliu" in response.text

    fresh = _propose(client, headers).json()
    _veto(session, account_id)  # tracking-ul pica intre depunere si aprobare
    response = client.post(f"/api/v1/proposals/{fresh['id']}/approve", headers=headers)
    assert response.status_code == 409 and "Oprită de consiliu" in response.text


# --- oprirea de urgenta din chat -----------------------------------------------------


@pytest.mark.parametrize(
    ("message", "command"),
    [
        ("Oprește campaniile!", "stop"),
        ("OPRESTE TOT", "stop"),
        ("stop campanii.", "stop"),
        ("  oprește   toate campaniile ", "stop"),
        ("Repornește agentul", "resume"),
        ("reia campaniile", "resume"),
        ("Oprește campaniile care pierd bani?", None),  # o intrebare, nu comanda
        ("de ce s-a oprit campania?", None),
        ("nu opri campaniile", None),
    ],
)
def test_doar_frazele_exacte_sunt_comenzi(message: str, command: str | None) -> None:
    assert queen.admin_command(message) == command


def _chat(client: TestClient, headers: dict[str, str], message: str) -> dict[str, Any]:
    response = client.post("/api/v1/queen/chat", headers=headers, json={"message": message})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_un_client_obisnuit_nu_poate_opri_platforma(
    client: TestClient, session: Session, agency_settings: Tenant, admins: None
) -> None:
    headers, _ = _login(client, session, "client@exemplu.ro")
    reply = _chat(client, headers, "Oprește campaniile")

    assert reply["reply"].startswith("Doar un administrator")
    assert emergency_stop.active_stop(session) is None


def test_adminul_opreste_tot_din_chat_si_reporneste(
    client: TestClient, session: Session, agency_settings: Tenant, admins: None,
    council: _Council,
) -> None:
    headers, account_id = _login(client, session, ADMIN)
    launch = _propose(client, headers).json()
    pause = ProposedChange(
        client_account_id=account_id, op=ChangeOp.PAUSE, resource="meta_ad/1",
        resource_type="ad", before={}, after={"status": "PAUSED"},
        projected_daily_spend=Decimal("0"), rationale="pauza", source_module="fatigue",
        status=ChangeStatus.PENDING,
    )
    session.add(pause)
    session.commit()

    reply = _chat(client, headers, "Oprește campaniile!")

    assert reply["reply"].startswith("Oprire de urgență activă.")
    assert "Propuneri care ar fi cheltuit, oprite: 1." in reply["reply"]
    session.expire_all()
    assert session.get(ProposedChange, launch["id"]).status is ChangeStatus.BLOCKED  # type: ignore[union-attr]
    assert session.get(ProposedChange, pause.id).status is ChangeStatus.PENDING  # type: ignore[union-attr]
    stop = emergency_stop.active_stop(session)
    assert stop is not None and stop.stopped_by == ADMIN

    # Cat e oprita: nimic nou, nici ziua, nici noaptea.
    assert _propose(client, headers).status_code == 423
    assert run_propose_job(client_account_id=account_id)["skipped"] == "oprire de urgență"

    reply = _chat(client, headers, "Repornește agentul")
    assert reply["reply"].startswith("Platforma a fost repornită")
    assert emergency_stop.active_stop(session) is None
    assert _propose(client, headers).status_code == 201
    assert _chat(client, headers, "reia campaniile")["reply"].startswith("Platforma nu era oprită")


def test_oprirea_pune_pe_pauza_campaniile_lansate_de_platforma(
    session: Session, agency_settings: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = ClientAccount(name="Client", tenant_id=agency_settings.id or 0)
    session.add(account)
    session.commit()
    for campaign in ("111", "222"):
        session.add(ProposedChange(
            client_account_id=account.id or 0, op=ChangeOp.CREATE_CAMPAIGN,
            resource="meta_ad_account/act_555", resource_type="campaign", before={}, after={},
            projected_daily_spend=Decimal("25"), rationale="lansare",
            source_module="campaign_launch", status=ChangeStatus.EXECUTED,
            execution_result={"campaign_id": campaign},
        ))
    session.commit()
    paused: list[str] = []

    class _Meta:
        async def pause_campaign(self, campaign_id: str) -> None:
            if campaign_id == "222":
                raise RuntimeError("Meta a refuzat")
            paused.append(campaign_id)

    class _Factory:
        def __init__(self, config: Any) -> None: ...

        def meta_mutations(self) -> _Meta:
            return _Meta()

    class _Live:
        provider_mode = ProviderMode.LIVE

    monkeypatch.setattr(emergency_stop, "_app_config_for", lambda account: _Live())
    monkeypatch.setattr(emergency_stop, "ProviderFactory", _Factory)

    report = emergency_stop.stop_all(session, by=ADMIN)

    assert paused == ["111"]
    assert report.paused == ["111"]
    assert report.failed == ["222: RuntimeError"]  # o campanie care pica nu le opreste pe celelalte
    assert session.exec(select(EmergencyStop)).one().stopped_by == ADMIN
    again = emergency_stop.stop_all(session, by=ADMIN)
    assert again.already_stopped and len(session.exec(select(EmergencyStop)).all()) == 1
