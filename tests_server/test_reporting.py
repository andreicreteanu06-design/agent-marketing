"""Teste pentru build_client_report() - agregare + narativa in limbaj simplu."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdPerformanceRecord,
    ChangeOp,
    ClientAccount,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.reporting.builder import build_client_report


def _client_account(
    session: Session,
    *,
    max_daily_spend: str = "50.00",
    default_lead_value: str = "300.00",
    objective: CampaignObjective = CampaignObjective.SALES,
) -> ClientAccount:
    tenant = Tenant(name="Agentie Test", api_key_hash=f"hash-reporting-{uuid.uuid4()}")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    account = ClientAccount(
        tenant_id=tenant.id,  # type: ignore[arg-type]
        name="Client Test",
        max_daily_spend=Decimal(max_daily_spend),
        default_lead_value=Decimal(default_lead_value),
        objective=objective,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_empty_client_report_has_zero_totals(session: Session) -> None:
    account = _client_account(session)
    report = build_client_report(session, account)

    assert report.total_spend == Decimal("0")
    assert report.total_revenue == Decimal("0")
    assert report.total_conversions == 0
    assert report.roas == 0.0
    assert report.ads == []
    assert report.decisions == []
    assert report.excluded_negative_keywords == 0


def test_report_aggregates_ad_performance(session: Session) -> None:
    account = _client_account(session)
    session.add(
        AdPerformanceRecord(
            client_account_id=account.id,
            ad_id="c_brand",
            platform=AdFatiguePlatform.GOOGLE,
            launch_time=datetime.now(tz=UTC),
            target_cpa=Decimal("10.00"),
            spend=Decimal("100.00"),
            revenue=Decimal("250.00"),
            conversions=5,
        )
    )
    session.add(
        AdPerformanceRecord(
            client_account_id=account.id,
            ad_id="tt_infeed",
            platform=AdFatiguePlatform.TIKTOK,
            launch_time=datetime.now(tz=UTC),
            target_cpa=Decimal("10.00"),
            spend=Decimal("50.00"),
            revenue=Decimal("50.00"),
            conversions=1,
        )
    )
    session.commit()

    report = build_client_report(session, account)
    assert report.total_spend == Decimal("150.00")
    assert report.total_revenue == Decimal("300.00")
    assert report.total_conversions == 6
    assert report.roas == 2.0
    assert len(report.ads) == 2


def _proposed_change(
    session: Session, account: ClientAccount, **overrides: object
) -> ProposedChange:
    defaults: dict[str, object] = dict(
        client_account_id=account.id,
        op=ChangeOp.UPDATE,
        resource="campaign/c_brand",
        resource_type="campaign",
        projected_daily_spend=Decimal("10.00"),
        rationale="motiv tehnic",
        source_module="budget",
    )
    defaults.update(overrides)
    change = ProposedChange(**defaults)  # type: ignore[arg-type]
    session.add(change)
    session.commit()
    session.refresh(change)
    return change


def test_narrative_for_fatigue_pause_hard(session: Session) -> None:
    account = _client_account(session)
    _proposed_change(
        session,
        account,
        resource="ad/c_dying",
        source_module="fatigue_monitor",
        after={"status": "paused", "verdict": "PAUSE_HARD", "platform": "google"},
        projected_daily_spend=Decimal("0"),
    )
    report = build_client_report(session, account)
    assert len(report.decisions) == 1
    assert "c_dying" in report.decisions[0].text
    assert "nicio conversie" in report.decisions[0].text


def test_narrative_for_budget_pause_vs_update(session: Session) -> None:
    account = _client_account(session)
    _proposed_change(
        session, account, resource="campaign/c_generic", projected_daily_spend=Decimal("0")
    )
    _proposed_change(
        session, account, resource="campaign/c_brand", projected_daily_spend=Decimal("22.45")
    )
    report = build_client_report(session, account)
    texts = " ".join(d.text for d in report.decisions)
    assert "redus la zero" in texts
    assert "22.45 lei/zi" in texts


def test_narrative_for_meta_liquidity(session: Session) -> None:
    account = _client_account(session)
    _proposed_change(
        session,
        account,
        resource="ad_set_group/merged_1",
        resource_type="ad_set",
        source_module="meta_liquidity",
        projected_daily_spend=Decimal("0"),
    )
    report = build_client_report(session, account)
    assert len(report.decisions) == 1
    assert "consolidate" in report.decisions[0].text


def test_negative_keywords_excluded_but_counted(session: Session) -> None:
    account = _client_account(session)
    for i in range(3):
        _proposed_change(
            session,
            account,
            resource=f"negative_keyword/termen{i}",
            resource_type="negative_keyword",
            source_module="negatives",
            op=ChangeOp.CREATE,
            projected_daily_spend=Decimal("0"),
        )
    report = build_client_report(session, account)
    assert report.decisions == []
    assert report.excluded_negative_keywords == 3


def test_decisions_ordered_most_recent_first(session: Session) -> None:
    account = _client_account(session)
    now = datetime.now(tz=UTC)
    old = _proposed_change(
        session, account, resource="campaign/old", projected_daily_spend=Decimal("5.00")
    )
    old.created_at = now - timedelta(days=2)
    session.add(old)
    new = _proposed_change(
        session, account, resource="campaign/new", projected_daily_spend=Decimal("5.00")
    )
    new.created_at = now
    session.add(new)
    session.commit()

    report = build_client_report(session, account)
    assert "new" in report.decisions[0].text
    assert "old" in report.decisions[1].text


def test_capacity_note_present_for_valid_budget(session: Session) -> None:
    account = _client_account(
        session, max_daily_spend="20.00", default_lead_value="180.00"
    )
    report = build_client_report(session, account)
    assert report.capacity_note is not None
    assert "target_cpa" in report.capacity_note


def test_capacity_note_none_when_budget_invalid(session: Session) -> None:
    """max_daily_spend=0 nu poate trece prin ClientAccountUpdate (Field(gt=0)),
    dar poate exista pe un rand mai vechi/creat direct - build_client_report nu
    trebuie sa crape, doar sa omita nota."""
    account = _client_account(session)
    account.max_daily_spend = Decimal("0")
    session.add(account)
    session.commit()

    report = build_client_report(session, account)
    assert report.capacity_note is None


def test_report_endpoint_returns_structured_data(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/clients",
        headers=auth_headers,
        json={"name": "Client Raport", "objective": "sales"},
    )
    client_id = created.json()["id"]

    response = client.get(f"/api/v1/clients/{client_id}/report", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["client_name"] == "Client Raport"
    assert body["objective"] == "sales"
    assert body["total_spend"] == "0"
    assert body["ads"] == []


def test_report_endpoint_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/clients/1/report").status_code == 401


def test_report_endpoint_not_owned_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/clients/999999/report", headers=auth_headers)
    assert response.status_code == 404
