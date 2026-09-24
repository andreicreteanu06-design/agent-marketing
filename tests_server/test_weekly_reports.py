"""Raportul saptamanal pe server: job-ul, salvarea si rutele citite de frontend.

Fara retea: in modul mock nu exista serii zilnice (decizie a proiectului), iar
unde e nevoie de ele, furnizorul Meta e inlocuit cu un dublu care raporteaza zi
cu zi.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.live.daily import DAILY_COLUMNS
from ppc_agent_server.jobs.weekly_report import run_weekly_report_job, run_weekly_reports_job
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    SubscriptionStatus,
    Tenant,
    WeeklyReport,
)

_WEEK_END = date(2026, 9, 20)


class _Daily:
    """Un furnizor live simulat, cu serii zilnice fixe."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def daily_campaign_performance(
        self, account_id: str, *, days: int, end_date: date | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame(self._rows, columns=DAILY_COLUMNS)


def _day(day: str, cost: float, conversions: float) -> dict[str, Any]:
    return {
        "date": date.fromisoformat(day),
        "arm_id": "as_1",
        "name": "Retargeting",
        "clicks": 40,
        "conversions": conversions,
        "cost": cost,
        "revenue": 0.0,
    }


def _tenant_with_client(
    session: Session, status: SubscriptionStatus, name: str
) -> ClientAccount:
    tenant = Tenant(name=f"Agentie {name}", api_key_hash=name, subscription_status=status)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    account = ClientAccount(tenant_id=tenant.id or 0, name=name, meta_ad_account_id="act_555")
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@pytest.fixture
def account(session: Session) -> ClientAccount:
    return _tenant_with_client(session, SubscriptionStatus.ACTIVE, "Client Auto")


def _executed(
    session: Session, account_id: int, when: datetime, *, simulated: bool = False
) -> None:
    session.add(
        ProposedChange(
            client_account_id=account_id,
            op=ChangeOp.PAUSE,
            resource="meta_ad_set/as_1",
            resource_type="ad_set",
            rationale="canibalizare",
            source_module="autonomous_evaluator",
            status=ChangeStatus.EXECUTED,
            decided_at=when,
            decided_by="client@exemplu.ro",
            execution_result={"simulated": True} if simulated else None,
        )
    )
    session.commit()


def _reports(session: Session, account_id: int) -> list[WeeklyReport]:
    return list(
        session.exec(
            select(WeeklyReport).where(WeeklyReport.client_account_id == account_id)
        ).all()
    )


# --- job-ul -----------------------------------------------------------------


def test_in_modul_mock_raportul_spune_ca_lipsesc_seriile_zilnice(
    account: ClientAccount, session: Session
) -> None:
    result = run_weekly_report_job(client_account_id=account.id or 0, week_end=_WEEK_END)

    (report,) = _reports(session, account.id or 0)
    payload = report.payload
    assert result["week_start"] == "2026-09-14"
    assert report.week_start == date(2026, 9, 14)
    assert payload["daily_performance_chart"] == []
    assert payload["summary_source"] == "template"
    assert any("mock" in gap for gap in payload["data_gaps"])


def test_cu_serii_zilnice_raportul_are_grafic_si_indicatori(
    account: ClientAccount, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _day("2026-09-15", 25.0, 2.0),
        _day("2026-09-16", 30.0, 3.0),
        _day("2026-09-09", 40.0, 2.0),
    ]
    monkeypatch.setattr(ProviderFactory, "meta", lambda self: _Daily(rows))

    run_weekly_report_job(client_account_id=account.id or 0, week_end=_WEEK_END)
    (report,) = _reports(session, account.id or 0)
    payload = report.payload

    assert len(payload["daily_performance_chart"]) == 7
    kpis = {kpi["key"]: kpi for kpi in payload["kpis"]}
    assert kpis["spend"]["current"] == 55.0
    assert kpis["cpa"]["current"] == 11.0
    assert [row["platform"] for row in payload["platform_breakdown"]] == ["meta_ads"]
    # Obiectiv implicit LEAD_GEN: fara venit raportat, ROAS e null, nu zero.
    assert kpis["roas"]["current"] is None


def test_deciziile_saptamanii_intra_in_jurnal_iar_cele_simulate_sunt_marcate(
    account: ClientAccount, session: Session
) -> None:
    account_id = account.id or 0
    _executed(session, account_id, datetime(2026, 9, 16, 10, tzinfo=UTC))
    _executed(session, account_id, datetime(2026, 9, 17, 10, tzinfo=UTC), simulated=True)
    _executed(session, account_id, datetime(2026, 9, 10, 10, tzinfo=UTC))  # saptamana anterioara

    run_weekly_report_job(client_account_id=account_id, week_end=_WEEK_END)
    (report,) = _reports(session, account_id)
    log = report.payload["ai_decisions_log"]

    assert [entry["applied"] for entry in log] == [True, False]
    assert log[0]["source"] == "evaluatorul autonom"


def test_regenerarea_inlocuieste_raportul_nu_il_dubleaza(
    account: ClientAccount, session: Session
) -> None:
    run_weekly_report_job(client_account_id=account.id or 0, week_end=_WEEK_END)
    run_weekly_report_job(client_account_id=account.id or 0, week_end=_WEEK_END)
    assert len(_reports(session, account.id or 0)) == 1


def test_cronul_de_luni_sare_peste_agentiile_suspendate(
    account: ClientAccount, session: Session
) -> None:
    suspended = _tenant_with_client(session, SubscriptionStatus.SUSPENDED, "Client Suspendat")
    result = run_weekly_reports_job(week_end=_WEEK_END)

    assert result["clients"] == 1
    assert _reports(session, suspended.id or 0) == []


def test_executia_simulata_a_agentiei_e_marcata_ca_simulata(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    """Fara marcaj, raportul clientului ar spune "aplicat" despre ceva neaplicat."""
    client_id = client.post(
        "/api/v1/clients", headers=auth_headers, json={"name": "Client Agentie"}
    ).json()["id"]
    change = ProposedChange(
        client_account_id=client_id,
        op=ChangeOp.PAUSE,
        resource="meta_ad_set/1",
        resource_type="ad_set",
        rationale="test",
        source_module="test",
    )
    session.add(change)
    session.commit()
    session.refresh(change)

    response = client.post(
        f"/api/v1/proposals/{change.id}/execute", headers=auth_headers, json={"confirm": True}
    )
    assert response.status_code == 200
    session.refresh(change)
    assert change.execution_result == {"simulated": True}


# --- rutele -----------------------------------------------------------------


@pytest.fixture
def reports_client(
    client: TestClient, agency_settings: Tenant
) -> tuple[TestClient, dict[str, str], int]:
    response = client.post(
        "/api/v1/signup",
        json={
            "name": "Client Rapoarte",
            "email": "rapoarte@exemplu.ro",
            "password": "parola-sigura-123",
        },
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    account_id = client.get("/api/v1/me", headers=headers).json()["account"]["id"]
    return client, headers, int(account_id)


def test_fara_niciun_raport_istoricul_e_gol_si_ultimul_da_404(
    reports_client: tuple[TestClient, dict[str, str], int],
) -> None:
    client, headers, _ = reports_client
    assert client.get("/api/v1/reports/weekly", headers=headers).json() == []
    assert client.get("/api/v1/reports/weekly/latest", headers=headers).status_code == 404


def test_generarea_la_cerere_intoarce_raportul_si_il_pastreaza(
    reports_client: tuple[TestClient, dict[str, str], int],
) -> None:
    client, headers, _ = reports_client
    generated = client.post("/api/v1/reports/weekly/generate", headers=headers)

    assert generated.status_code == 200
    body = generated.json()
    for key in ("executive_summary", "ai_decisions_log", "daily_performance_chart", "kpis"):
        assert key in body
    week_start = body["period"]["start"]

    history = client.get("/api/v1/reports/weekly", headers=headers).json()
    assert [item["week_start"] for item in history] == [week_start]
    latest = client.get("/api/v1/reports/weekly/latest", headers=headers)
    assert latest.json()["period"] == body["period"]
    by_week = client.get(f"/api/v1/reports/weekly/{week_start}", headers=headers)
    assert by_week.status_code == 200


def test_o_saptamana_neincheiata_nu_se_poate_raporta(
    reports_client: tuple[TestClient, dict[str, str], int],
) -> None:
    client, headers, _ = reports_client
    today = datetime.now(tz=UTC).date().isoformat()
    response = client.post(
        "/api/v1/reports/weekly/generate", headers=headers, params={"week_end": today}
    )
    assert response.status_code == 422


def test_rapoartele_altui_client_nu_se_vad(
    reports_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = reports_client
    session.add(
        WeeklyReport(
            client_account_id=account_id + 999,
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
            payload={"summary_source": "template"},
        )
    )
    session.commit()

    assert client.get("/api/v1/reports/weekly/latest", headers=headers).status_code == 404
    assert client.get("/api/v1/reports/weekly/2026-09-14", headers=headers).status_code == 404
    assert client.get("/api/v1/reports/weekly", headers=headers).json() == []


def test_rapoartele_cer_autentificare(client: TestClient) -> None:
    assert client.get("/api/v1/reports/weekly").status_code == 401
    assert client.post("/api/v1/reports/weekly/generate").status_code == 401
