"""Teste pentru poarta HITL: GET /proposals/{client_id}, POST /proposals/{id}/execute.

Nu exista (inca) un endpoint care sa creeze ProposedChange automat din plan
(echivalentul 'propose' din CLI e in afara listei de endpoint-uri cerute) -
testele insereaza randurile direct prin sesiune, ca sa izoleze comportamentul
endpoint-urilor de citit/executat.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.models import ChangeOp, ChangeStatus, ProposedChange, Tenant


def _create_client(
    client: TestClient, auth_headers: dict[str, str], max_daily_spend: str = "60.00"
) -> int:
    response = client.post(
        "/api/v1/clients",
        headers=auth_headers,
        json={"name": "Client Test", "max_daily_spend": max_daily_spend},
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def _add_change(
    session: Session,
    client_id: int,
    *,
    spend: str = "10.00",
    status: ChangeStatus = ChangeStatus.PENDING,
) -> ProposedChange:
    change = ProposedChange(
        client_account_id=client_id,
        op=ChangeOp.UPDATE,
        resource="campaign/c_brand",
        resource_type="campaign",
        projected_daily_spend=Decimal(spend),
        rationale="Thompson Sampling: P(cel mai bun)=1.000",
        source_module="budget",
        status=status,
    )
    session.add(change)
    session.commit()
    session.refresh(change)
    return change


def test_list_pending_proposals(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers)
    _add_change(session, client_id)
    _add_change(session, client_id)
    _add_change(session, client_id, status=ChangeStatus.EXECUTED)  # nu apare in lista

    response = client.get(f"/api/v1/proposals/{client_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(item["status"] == "pending" for item in body)


def test_execute_without_confirm_returns_403(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers)
    change = _add_change(session, client_id)

    response = client.post(
        f"/api/v1/proposals/{change.id}/execute", headers=auth_headers, json={}
    )
    assert response.status_code == 403
    assert "confirmare" in response.json()["detail"]


def test_execute_with_confirm_marks_executed(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers)
    change = _add_change(session, client_id, spend="10.00")

    response = client.post(
        f"/api/v1/proposals/{change.id}/execute", headers=auth_headers, json={"confirm": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["decided_at"] is not None


def test_execute_over_absolute_limit_returns_409(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers, max_daily_spend="20.00")
    change = _add_change(session, client_id, spend="25.00")  # peste limita clientului

    response = client.post(
        f"/api/v1/proposals/{change.id}/execute", headers=auth_headers, json={"confirm": True}
    )
    assert response.status_code == 409


def test_execute_checks_cumulative_committed_spend_not_just_this_row(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    """Doua propuneri, fiecare sub plafon individual, dar impreuna peste - a doua refuzata."""
    client_id = _create_client(client, auth_headers, max_daily_spend="30.00")
    first = _add_change(session, client_id, spend="20.00")
    second = _add_change(session, client_id, spend="20.00")

    ok = client.post(
        f"/api/v1/proposals/{first.id}/execute", headers=auth_headers, json={"confirm": True}
    )
    assert ok.status_code == 200

    blocked = client.post(
        f"/api/v1/proposals/{second.id}/execute", headers=auth_headers, json={"confirm": True}
    )
    assert blocked.status_code == 409


def test_proposals_are_tenant_isolated(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers)
    change = _add_change(session, client_id)

    other_tenant = Tenant(name="Alta agentie", api_key_hash="alt-hash-proposals")
    session.add(other_tenant)
    session.commit()

    from ppc_agent_server.auth import hash_api_key

    other_headers = {"Authorization": "Bearer pk_altcineva"}
    other_tenant.api_key_hash = hash_api_key("pk_altcineva")
    session.add(other_tenant)
    session.commit()

    assert (
        client.get(f"/api/v1/proposals/{client_id}", headers=other_headers).status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/proposals/{change.id}/execute", headers=other_headers, json={"confirm": True}
        ).status_code
        == 404
    )


def test_proposal_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/proposals/1").status_code == 401
    assert client.post("/api/v1/proposals/1/execute", json={"confirm": True}).status_code == 401
