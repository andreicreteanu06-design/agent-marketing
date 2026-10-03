"""Scutul financiar al pilotului: ``MAX_DAILY_SPEND_RON`` si hard-stop-ul din motor.

Trei centuri, fiecare testata separat, toate fara retea:

1. motorul refuza orice schimbare care, singura, trece de plafon - INAINTE de provider;
2. ruta refuza cand TOATA platforma (toti clientii) ar trece de plafonul global;
3. ruta refuza un cont Meta in alta moneda decat plafonul (RON).

Plus: oprirea cheltuielii (``PAUSE``) nu se blocheaza niciodata, si orice refuz
lasa o alerta CRITICAL in log-ul JSON de audit.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.errors import SpendLimitExceeded
from ppc_agent.services.execution_engine import execute_proposal
from ppc_agent_server.audit_log import JsonFormatter
from ppc_agent_server.models import ChangeOp, ChangeStatus, ClientAccount, ProposedChange
from ppc_agent_server.settings import get_server_settings
from tests_server import test_proposal_execution as _hitl_tests
from tests_server.test_campaign_launch import _spec
from tests_server.test_proposal_execution import (
    _add_pending,
    _FakeMetaProvider,
    _GraphApiStub,
    _proposal,
)

# Fixture-urile HITL (server live, Graph API interceptat), refolosite ca atare.
graph_api = _hitl_tests.graph_api
hitl = _hitl_tests.hitl
meta_live = _hitl_tests.meta_live

_CAP = Decimal("50")


# --- motorul: hard-stop inainte de platforma ------------------------------------


def test_motorul_opreste_un_buget_peste_plafon_fara_sa_atinga_platforma(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _FakeMetaProvider()
    proposal = _proposal(op=ChangeOp.UPDATE, spend="50.01")

    with caplog.at_level(logging.CRITICAL), pytest.raises(SpendLimitExceeded):
        execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)

    assert not provider.touched
    [alert] = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert alert.event == "spend_limit_exceeded"  # type: ignore[attr-defined]
    assert alert.cap == "50"  # type: ignore[attr-defined]


def test_motorul_lasa_exact_plafonul() -> None:
    provider = _FakeMetaProvider()
    proposal = _proposal(op=ChangeOp.UPDATE, spend="50")
    execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.budgets == [("23848", Decimal("50"))]


def test_pauza_nu_se_blocheaza_niciodata() -> None:
    """Oprirea cheltuielii trece chiar si cu plafon minuscul si suma declarata mare."""
    provider = _FakeMetaProvider()
    proposal = _proposal(op=ChangeOp.PAUSE, spend="999")
    execute_proposal(
        proposal, provider, current_status="pending", max_daily_spend=Decimal("0.01")
    )
    assert provider.paused_adsets == ["23848"]


def _launch(*, approved: str, spec_budget: str) -> ProposedChange:
    return ProposedChange(
        client_account_id=1,
        op=ChangeOp.CREATE_CAMPAIGN,
        resource="meta_ad_account/act_1",
        resource_type="ad_account",
        projected_daily_spend=Decimal(approved),
        after=_spec(daily_budget=Decimal(spec_budget)).to_payload(),
        rationale="test",
        source_module="test",
    )


def test_o_lansare_cu_buget_umflat_in_specificatie_nu_pleaca() -> None:
    """S-a aprobat 20/zi, dar ``after`` (modificat in DB) cere 45: nimic nu se lanseaza."""
    provider = _FakeMetaProvider()
    with pytest.raises(SpendLimitExceeded, match="s-a aprobat 20"):
        execute_proposal(
            _launch(approved="20", spec_budget="45"),
            provider,  # type: ignore[arg-type]
            current_status="pending",
            max_daily_spend=_CAP,
        )
    assert not provider.touched


def test_o_lansare_peste_plafon_nu_pleaca() -> None:
    provider = _FakeMetaProvider()
    with pytest.raises(SpendLimitExceeded, match="depaseste plafonul"):
        execute_proposal(
            _launch(approved="80", spec_budget="80"),
            provider,  # type: ignore[arg-type]
            current_status="pending",
            max_daily_spend=_CAP,
        )
    assert not provider.touched


# --- ruta: plafonul global, pe toata platforma -----------------------------------


def _other_client_spent(session: Session, account_id: int, amount: str) -> None:
    """Alt client al aceleiasi platforme, cu ``amount``/zi deja executat."""
    mine = session.get(ClientAccount, account_id)
    assert mine is not None
    other = ClientAccount(
        tenant_id=mine.tenant_id, name="Alt client", max_daily_spend=Decimal("500")
    )
    session.add(other)
    session.commit()
    session.refresh(other)
    change = _proposal(other.id or 0, op=ChangeOp.UPDATE, spend=amount)
    change.status = ChangeStatus.EXECUTED
    session.add(change)
    session.commit()


def test_plafonul_global_insumeaza_toti_clientii(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Clientul are loc (20 <= 50), dar platforma are deja 40: 60 > 50 -> 409."""
    client, headers, account_id = hitl
    _other_client_spent(session, account_id, "40")
    proposal_id = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="20")

    with caplog.at_level(logging.CRITICAL):
        response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert graph_api.calls == []
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING
    assert any(getattr(r, "scope", None) == "platforma" for r in caplog.records)


def test_plafonul_global_se_citeste_din_env(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MAX_DAILY_SPEND_RON=10``: 15/zi nu trece, desi clientul are plafon 50."""
    monkeypatch.setenv("MAX_DAILY_SPEND_RON", "10")
    get_server_settings.cache_clear()
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="15")

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert graph_api.calls == []


def test_pauza_trece_chiar_cu_platforma_peste_plafon(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """Platforma a ajuns (din alt motiv) la 90 > 50: oprirea tot trebuie sa mearga."""
    client, headers, account_id = hitl
    _other_client_spent(session, account_id, "90")
    proposal_id = _add_pending(session, account_id, op=ChangeOp.PAUSE)

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert len(graph_api.calls) == 1


def test_un_cont_meta_in_alta_moneda_nu_se_atinge(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plafonul e in lei; 50 pe un cont in EUR ar fi ~250 lei."""
    monkeypatch.setenv("PPC_META_CURRENCY", "EUR")
    client, headers, account_id = hitl
    proposal_id = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="10")

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert "EUR" in response.json()["detail"]
    assert graph_api.calls == []


# --- log-ul de audit ----------------------------------------------------------


def test_alerta_iese_ca_o_linie_json_cu_campurile_evenimentului() -> None:
    record = logging.makeLogRecord(
        {
            "name": "ppc_agent_server.spend_guard",
            "levelno": logging.CRITICAL,
            "levelname": "CRITICAL",
            "msg": "SPEND GUARD: plafon %s depasit",
            "args": ("platforma",),
            "event": "spend_limit_exceeded",
            "total": "60",
        }
    )
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "CRITICAL"
    assert line["msg"] == "SPEND GUARD: plafon platforma depasit"
    assert line["event"] == "spend_limit_exceeded"
    assert line["total"] == "60"
    assert "args" not in line


def test_un_buget_nou_pe_acelasi_set_il_inlocuieste_pe_cel_vechi(
    hitl: tuple[TestClient, dict[str, str], int],
    session: Session,
    meta_live: None,
    graph_api: _GraphApiStub,
) -> None:
    """Setul are deja 40/zi executat; 48/zi pe ACELASI set inseamna 48, nu 88 > 50."""
    client, headers, account_id = hitl
    executed = _proposal(account_id, op=ChangeOp.UPDATE, spend="40")
    executed.status = ChangeStatus.EXECUTED
    session.add(executed)
    session.commit()
    same_set = _add_pending(session, account_id, op=ChangeOp.UPDATE, spend="48")
    other_set = _add_pending(
        session, account_id, op=ChangeOp.UPDATE, resource="meta_ad_set/777", spend="5"
    )

    approved = client.post(f"/api/v1/proposals/{same_set}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    # Acum sunt angajati 48: inca 5 pe alt set ar insemna 53 > 50.
    refused = client.post(f"/api/v1/proposals/{other_set}/approve", headers=headers)
    assert refused.status_code == 409
