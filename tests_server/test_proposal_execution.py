"""Motorul de executie si endpoint-urile de aprobare/respingere.

Motorul se testeaza cu un provider dublu (Protocol ingust, fara retea);
endpoint-urile prin HTTP. Invariantul central: o propunere ajunge EXECUTED doar
daca platforma a confirmat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.services.execution_engine import (
    NoExecutorError,
    ProposalNotExecutableError,
    execute_proposal,
)
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ProposedChange,
    Tenant,
)


class _FakeProvider:
    """Provider dublu: retine ce i s-a cerut, sau pica la comanda."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.paused: list[str] = []
        self.budgets: list[tuple[str, Decimal]] = []
        self._fail = fail

    def pause_ad(self, ad_id: str) -> None:
        if self._fail:
            raise self._fail
        self.paused.append(ad_id)

    def scale_budget(self, campaign_id: str, new_daily_budget: Decimal) -> None:
        if self._fail:
            raise self._fail
        self.budgets.append((campaign_id, new_daily_budget))


def _proposal(
    client_account_id: int = 1,
    *,
    op: ChangeOp = ChangeOp.PAUSE,
    resource_type: str = "ppc_keyword",
    spend: str = "0",
) -> ProposedChange:
    return ProposedChange(
        client_account_id=client_account_id,
        op=op,
        resource="service auto",
        resource_type=resource_type,
        projected_daily_spend=Decimal(spend),
        rationale="test",
        source_module="test",
    )


# --- motorul ----------------------------------------------------------------


def test_pauza_ajunge_la_provider() -> None:
    provider = _FakeProvider()
    result = execute_proposal(_proposal(), provider, current_status="pending")
    assert result.executed is True
    assert provider.paused == ["service auto"]


def test_actualizarea_de_buget_trimite_suma() -> None:
    provider = _FakeProvider()
    proposal = _proposal(op=ChangeOp.UPDATE, resource_type="keyword_budget", spend="120.50")
    execute_proposal(proposal, provider, current_status="pending")
    assert provider.budgets == [("service auto", Decimal("120.50"))]


def test_o_propunere_ne_pending_nu_se_re_executa() -> None:
    """Un dublu-click pe aprobare nu trebuie sa dubleze o schimbare de buget."""
    with pytest.raises(ProposalNotExecutableError):
        execute_proposal(_proposal(), _FakeProvider(), current_status="executed")


def test_tip_fara_executor_nu_se_aplica_pe_aproape() -> None:
    proposal = _proposal(resource_type="meta_campaign")
    with pytest.raises(NoExecutorError, match="meta_campaign"):
        execute_proposal(proposal, _FakeProvider(), current_status="pending")


def test_esecul_platformei_devine_rezultat_nu_exceptie() -> None:
    """Propunerea trebuie marcata FAILED cu motiv, nu sa arunce in sus."""
    provider = _FakeProvider(fail=RuntimeError("token expirat"))
    result = execute_proposal(_proposal(), provider, current_status="pending")
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


def _add_pending(session: Session, account_id: int) -> int:
    change = _proposal(account_id)
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
    assert rows[0]["resource"] == "service auto"


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


def test_aprobarea_raporteaza_lipsa_providerului_si_lasa_propunerea_in_asteptare(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    """Azi niciun provider nu stie sa aplice mutatii - vezi _mutation_provider.

    501, nu FAILED: n-am incercat si n-am esuat, n-avem cu ce. Propunerea ramane
    PENDING, ca sa poata fi aplicata manual sau automat mai tarziu.
    """
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)
    assert response.status_code == 501

    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_o_propunere_deja_decisa_nu_se_mai_aproba(
    hitl: tuple[TestClient, dict[str, str], int], session: Session
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
    assert response.status_code in (409, 501)
    assert (
        session.exec(
            select(ProposedChange).where(ProposedChange.id == proposal_id)
        ).one().status
        is ChangeStatus.EXECUTED
    )
