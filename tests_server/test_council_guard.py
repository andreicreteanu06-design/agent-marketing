"""Puntea consiliu -> tura de noapte: deciziile din chat se aplica in campanii.

Jobul PPC de noapte (``run_propose_job``) citeste memoria consiliului (``MemoryStream``,
7 zile) si raportul Tehnicianului de acum (``services/council_guard.py``): un veto pe
bani opreste tot ce e calculat pe conversii, o taietura a CFO-ului nu lasa Kelly sa
creasca bugetul. Ce se opreste ramane in DB, ``blocked``, cu motivul - clientul il vede.
Furnizorii sunt cei mock: Kelly urca plafonul de 50 RON la 60,87 RON (x1,217).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import ppc_agent_server.jobs.tasks as tasks_module
from ppc_agent_server.jobs.tasks import run_propose_job
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdPerformanceRecord,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    MemoryStream,
    ProposedChange,
    TrackingEvidence,
)
from ppc_agent_server.services.council import QueenCouncil, build_financial_snapshot
from ppc_agent_server.services.council_guard import CFO_NIGHT_CODE, council_constraints
from ppc_agent_server.services.queen_signals import DbMemory
from ppc_agent_server.services.technician import evaluate_technical_health
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_council import (
    LOSING,
    _ad,
    _directive,
    _finances,
    _Static,
    _StaticTechnical,
)
from tests_server.test_queen_router import signed_in  # noqa: F401 - fixture
from tests_server.test_technician import BROKEN_TAG, GA4_DOWN
from tests_server.test_technician import _signals as _technical

NOW = datetime.now(tz=UTC)
#: Cum scrie consiliul veto-ul in memorie (``council.memories_from_reply``).
PIXEL_VETO = (
    "a pus veto: tracking-ul e picat pe Pixelul Meta: evenimentele «Lead» n-au ajuns la "
    "platformă cu răspuns 2xx (test E2E, 26 septembrie)"
)
CFO_CUT = "a tăiat creșterea bugetului, pentru că contul nu e rentabil"


def _remember(
    session: Session,
    account: ClientAccount,
    role: str,
    decision: str,
    code: str,
    *,
    days_ago: float = 0,
    observation: str = "",
    at: datetime | None = None,
) -> None:
    session.add(
        MemoryStream(
            client_account_id=account.id or 0,
            timestamp=at or NOW - timedelta(days=days_ago),
            agent_role=role,
            topic="budget",
            decision=decision,
            observation=observation,
            code=code,
        )
    )
    session.commit()


def _memory(session: Session, account: ClientAccount, code: str) -> list[MemoryStream]:
    return list(
        session.exec(
            select(MemoryStream)
            .where(MemoryStream.client_account_id == account.id)
            .where(MemoryStream.code == code)
        ).all()
    )


def _ads(session: Session, account: ClientAccount, *, spend: str, conversions: int) -> None:
    """Cifrele CFO-ului: o reclama Meta cu tinta de 80 RON pe conversie."""
    session.add(
        AdPerformanceRecord(
            client_account_id=account.id or 0,
            ad_id=f"ad-{spend}-{conversions}",
            platform=AdFatiguePlatform.META,
            launch_time=NOW - timedelta(days=20),
            spend=Decimal(spend),
            target_cpa=Decimal("80"),
            conversions=conversions,
        )
    )
    session.commit()


def _e2e(session: Session, account: ClientAccount, *, hours_ago: float, meta_ok: bool) -> None:
    """Un test sintetic de noapte, cu evenimentul Meta «Lead» din contract."""
    session.add(
        TrackingEvidence(
            client_account_id=account.id or 0,
            url="https://autofix.ro/",
            started_at=NOW - timedelta(hours=hours_ago),
            navigation_status=200,
            cta_ok=True,
            meta_transport_ok=meta_ok,
            failure_reason=None if meta_ok else "EVENT_MISMATCH",
            evidence={"verdict": {"meta": {"expected_events": ["Lead"]}}},
        )
    )
    session.commit()


def _pending(session: Session, account: ClientAccount, **fields: Any) -> ProposedChange:
    """O propunere din noptile trecute, inca in asteptarea clientului."""
    row = ProposedChange(
        client_account_id=account.id or 0,
        status=ChangeStatus.PENDING,
        created_at=NOW - timedelta(days=2),
        **fields,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _launch(session: Session, account: ClientAccount) -> ProposedChange:
    return _pending(
        session,
        account,
        op=ChangeOp.CREATE_CAMPAIGN,
        resource="meta_campaign/nou",
        resource_type="campaign",
        before={"brief": "lansare"},
        after={"daily_budget": "20"},
        projected_daily_spend=Decimal("20"),
        rationale="Lansare Meta",
        source_module="campaign_launch",
    )


def _tonight(session: Session, account: ClientAccount) -> list[ProposedChange]:
    return list(
        session.exec(
            select(ProposedChange)
            .where(ProposedChange.client_account_id == account.id)
            .where(ProposedChange.created_at >= NOW - timedelta(hours=1))
        ).all()
    )


# --- veto-ul Tehnicianului -------------------------------------------------------------


def test_a_dead_meta_pixel_reported_yesterday_stops_every_money_decision(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    account = _client_account(session)
    _remember(session, account, "cto", PIXEL_VETO, "ATTRIBUTION_BROKEN", days_ago=1)
    launch = _launch(session, account)
    old_budget = _pending(
        session,
        account,
        op=ChangeOp.UPDATE,
        resource="meta_ad_set/vechi",
        resource_type="ad_set",
        after={"daily_budget": "25"},
        projected_daily_spend=Decimal("25"),
        rationale="Thompson de alaltaieri",
        source_module="budget",
    )

    with caplog.at_level(logging.WARNING, logger="ppc_agent_server.jobs.tasks"):
        result = run_propose_job(client_account_id=account.id or 0)

    rows = _tonight(session, account)
    by_module: dict[str, set[ChangeStatus]] = {}
    for row in rows:
        by_module.setdefault(row.source_module, set()).add(row.status)
    # Tot ce e calculat pe conversii se opreste; negativele (pe intentie) merg mai departe.
    assert by_module["budget"] == {ChangeStatus.BLOCKED}
    assert by_module["meta_liquidity"] == {ChangeStatus.BLOCKED}
    assert by_module["negatives"] == {ChangeStatus.PENDING}
    blocked = [row for row in rows if row.status == ChangeStatus.BLOCKED]
    assert result["created"] == len(rows) - len(blocked)
    assert result["total_projected_daily_spend"] == "0"
    assert result["council"]["blocked"] == len(blocked)
    assert result["council"]["blocked_pending"] == 2

    row = blocked[0]
    assert row.decided_by == "consiliu" and row.decided_at is not None
    assert row.error_message is not None
    assert row.error_message.startswith(
        "Oprită de consiliu. Ieri, Tehnicianul a pus veto: tracking-ul e picat pe Pixelul Meta"
    )
    assert row.error_message.endswith("după ce testul E2E confirmă reparația.")
    assert row.before["council"]["code"] == "ATTRIBUTION_BROKEN"
    assert row.before["council"]["restriction"] == "money_veto"

    # Ce astepta deja clientul: lansarea si planul de buget vechi, oprite si ele.
    for pending in (launch, old_budget):
        session.refresh(pending)
        assert pending.status == ChangeStatus.BLOCKED
        assert pending.error_message is not None and "Pixelul Meta" in pending.error_message
    assert launch.before["brief"] == "lansare"  # contextul lansarii ramane

    [record] = [r for r in caplog.records if r.getMessage().startswith("[Consiliu]")]
    assert "Veto pe bani: Ieri, Tehnicianul a pus veto" in record.getMessage()


def test_a_broken_pixel_seen_tonight_stops_the_budgets_without_anyone_asking(
    session: Session,
) -> None:
    account = _client_account(session)
    _e2e(session, account, hours_ago=2, meta_ok=False)

    result = run_propose_job(client_account_id=account.id or 0)

    assert result["council"]["note"].startswith(
        "Veto pe bani: Tehnicianul a pus veto azi: Tracking-ul e picat pe Pixelul Meta"
    )
    budget = [row for row in _tonight(session, account) if row.source_module == "budget"]
    assert budget and {row.status for row in budget} == {ChangeStatus.BLOCKED}


def test_the_veto_is_lifted_by_an_e2e_test_that_passes_after_it(session: Session) -> None:
    account = _client_account(session)
    _remember(session, account, "cto", PIXEL_VETO, "ATTRIBUTION_BROKEN", days_ago=2)
    _e2e(session, account, hours_ago=3, meta_ok=True)

    result = run_propose_job(client_account_id=account.id or 0)

    # Conditia de rediscutare s-a indeplinit: algoritmul e liber, iar veto-ul se invalideaza.
    assert {row.status for row in _tonight(session, account)} == {ChangeStatus.PENDING}
    assert result["council"]["note"] == ""
    [lifted] = result["council"]["lifted"]
    assert lifted.startswith("Azi, Tehnicianul a ridicat veto-ul: testul E2E din ")
    assert lifted.endswith("a trecut, conversiile ajung din nou la platforme.")
    [row] = _memory(session, account, "lifted:ATTRIBUTION_BROKEN")
    assert row.agent_role == "cto"

    # Noaptea urmatoare, veto-ul e invalidat: nicio restrictie, nicio ridicare noua.
    assert "council" not in run_propose_job(client_account_id=account.id or 0)


def test_a_passing_test_from_before_the_veto_proves_nothing(session: Session) -> None:
    account = _client_account(session)
    _e2e(session, account, hours_ago=60, meta_ok=True)
    _remember(session, account, "cto", PIXEL_VETO, "ATTRIBUTION_BROKEN", days_ago=1)

    result = run_propose_job(client_account_id=account.id or 0)

    assert result["council"]["blocked"] > 0


def test_a_veto_older_than_seven_days_is_forgotten(session: Session) -> None:
    account = _client_account(session)
    _remember(session, account, "cto", PIXEL_VETO, "ATTRIBUTION_BROKEN", days_ago=8)

    result = run_propose_job(client_account_id=account.id or 0)

    assert "council" not in result


# --- restrictia CFO-ului ------------------------------------------------------------------


def test_a_cfo_cut_keeps_kelly_from_raising_the_budget(session: Session) -> None:
    account = _client_account(session, max_daily_spend="50.00")
    _remember(
        session, account, "cfo", CFO_CUT, "budget", days_ago=2,
        observation="CPA-ul e 175 RON, peste ținta de 80 RON",
    )
    _ads(session, account, spend="1750", conversions=10)  # cifrele de azi: tot pe pierdere
    launch = _launch(session, account)

    result = run_propose_job(client_account_id=account.id or 0)

    budget = [row for row in _tonight(session, account) if row.source_module == "budget"]
    assert {row.status for row in budget} == {ChangeStatus.PENDING}
    total = sum((row.projected_daily_spend for row in budget), Decimal("0"))
    # Kelly voia 60,87 RON/zi; CFO-ul tine bugetul la cel aprobat, 50 RON.
    assert Decimal("49.90") <= total <= Decimal("50.00")
    assert Decimal(result["total_projected_daily_spend"]) <= Decimal("50.00")
    capped = [row for row in budget if row.projected_daily_spend > 0]
    assert result["council"]["capped"] == len(capped) > 0
    row = capped[0]
    assert row.rationale.startswith("[Consiliu] Buget plafonat la ")
    assert "Acum 2 zile, CFO-ul a tăiat creșterea bugetului" in row.rationale
    assert row.after["daily_budget"] == str(row.projected_daily_spend)
    proposed = Decimal(row.before["council"]["proposed_daily_budget"])
    assert proposed > row.projected_daily_spend
    # Nicio campanie noua cat timp CFO-ul spune ca nu cheltuim in plus.
    session.refresh(launch)
    assert launch.status == ChangeStatus.BLOCKED
    assert launch.error_message is not None
    assert launch.error_message.endswith("Cheltuiala nu crește până nu se ridică restricția.")


def test_a_cfo_cut_without_data_does_not_block_a_first_launch(session: Session) -> None:
    """Fara conversii, CFO-ul taie cresterea bugetului - dar un prim test e felul in care
    se strang datele; altfel un client nou n-ar putea lansa niciodata."""
    account = _client_account(session, max_daily_spend="50.00")
    _remember(session, account, "cfo", CFO_CUT, "budget", days_ago=1)
    launch = _launch(session, account)

    run_propose_job(client_account_id=account.id or 0)

    session.refresh(launch)
    assert launch.status == ChangeStatus.PENDING


def test_a_cfo_cut_leaves_a_plan_that_does_not_grow_untouched(session: Session) -> None:
    # La 500 RON aprobati, Kelly se opreste la 500: nu e nicio crestere de taiat.
    account = _client_account(session, max_daily_spend="500.00")
    _remember(session, account, "cfo", CFO_CUT, "budget", days_ago=1)

    result = run_propose_job(client_account_id=account.id or 0)

    assert result["council"]["capped"] == 0
    assert result["total_projected_daily_spend"] == "500.00"


def test_the_cfo_lifts_its_cut_once_the_account_is_profitable_again(session: Session) -> None:
    account = _client_account(session)
    _remember(session, account, "cfo", CFO_CUT, "budget", days_ago=2)
    _remember(session, account, "cfo", "a tăiat un test de interese", "paid_targeting", days_ago=1)
    _ads(session, account, spend="620", conversions=9)  # CPA 68,89 RON, sub tinta de 80

    result = run_propose_job(client_account_id=account.id or 0)

    # Algoritmul e liber din nou: Kelly urca la 60,87 RON, nimic plafonat.
    assert result["total_projected_daily_spend"] == "60.87"
    assert (result["council"]["note"], result["council"]["capped"]) == ("", 0)
    assert result["council"]["lifted"] == [
        "Azi, CFO-ul a ridicat restricția pe buget: CPA-ul contului a coborât la 68,89 RON, "
        "sub ținta de 80 RON."
    ]
    # O singura ridicare pentru toate taieturile CFO-ului: aceeasi conditie.
    [row] = _memory(session, account, "lifted:cfo")
    assert row.agent_role == "cfo"


def test_after_a_lift_a_relapse_is_stopped_by_the_night_cfo_not_by_the_old_cut(
    session: Session,
) -> None:
    account = _client_account(session)
    _remember(session, account, "cfo", CFO_CUT, "budget", days_ago=2)
    _ads(session, account, spend="620", conversions=9)
    assert run_propose_job(client_account_id=account.id or 0)["council"]["lifted"]

    # Contul recade pe pierdere: taietura veche ramane invalidata, dar CFO-ul de noapte
    # judeca singur contul si opreste din nou cresterea - fara sa astepte chatul.
    _ads(session, account, spend="3000", conversions=1)
    relapse = run_propose_job(client_account_id=account.id or 0)

    assert relapse["council"]["imposed"] == [
        "Azi, CFO-ul a oprit automat creșterea bugetului în tura de noapte: CPA-ul contului e "
        "362 RON, peste ținta de 80 RON."
    ]
    assert relapse["council"]["note"].startswith(
        "Bugetul nu crește: Azi, CFO-ul a oprit automat creșterea bugetului"
    )
    assert relapse["council"]["capped"] > 0
    assert relapse["total_projected_daily_spend"] == "50.00"


# --- CFO-ul de noapte: judeca singur, fara chat ------------------------------------------


def test_the_night_cfo_stops_the_growth_of_a_losing_account_and_tells_the_chat(
    session: Session,
) -> None:
    account = _client_account(session)
    _ads(session, account, spend="1500", conversions=6)  # CPA 250 RON, tinta 80

    first = run_propose_job(client_account_id=account.id or 0)

    decision = (
        "a oprit automat creșterea bugetului în tura de noapte: CPA-ul contului e 250 RON, "
        "peste ținta de 80 RON"
    )
    assert first["council"]["imposed"] == [f"Azi, CFO-ul {decision}."]
    # Kelly voia 60,87 RON/zi; CFO-ul tine bugetul la cel aprobat.
    assert Decimal(first["total_projected_daily_spend"]) <= Decimal("50.00")
    assert first["council"]["capped"] > 0
    [row] = _memory(session, account, CFO_NIGHT_CODE)
    assert (row.agent_role, row.decision) == ("cfo", decision)
    # In chat, a doua zi: consiliul o gaseste in Contextul Istoric.
    assert any(entry.decision == decision for entry in DbMemory(session).recall(account.id or 0))

    # A doua noapte, tot pe pierdere: restrictia e deja activa - nicio decizie dubla.
    second = run_propose_job(client_account_id=account.id or 0)
    assert second["council"]["imposed"] == []
    assert second["council"]["note"].startswith(
        "Bugetul nu crește: Azi, CFO-ul a oprit automat creșterea bugetului"
    )
    assert len(_memory(session, account, CFO_NIGHT_CODE)) == 1


def test_the_night_cfo_never_judges_on_numbers_without_tracking(session: Session) -> None:
    account = _client_account(session)
    _ads(session, account, spend="1500", conversions=6)
    _e2e(session, account, hours_ago=2, meta_ok=False)

    result = run_propose_job(client_account_id=account.id or 0)

    # Cu pixelul picat, CPA-ul mare e fals: veto-ul Tehnicianului opreste bugetele, nu CFO-ul.
    assert result["council"]["note"].startswith("Veto pe bani: Tehnicianul a pus veto azi")
    assert result["council"]["imposed"] == []
    assert _memory(session, account, CFO_NIGHT_CODE) == []


def test_the_night_cfo_waits_for_enough_conversions(session: Session) -> None:
    account = _client_account(session)
    _ads(session, account, spend="900", conversions=2)  # sub 5 conversii: nu judeca

    assert "council" not in run_propose_job(client_account_id=account.id or 0)


def test_the_night_cfo_judges_a_sales_account_by_roas() -> None:
    snapshot = build_financial_snapshot(
        _finances(
            ads=(_ad(spend="1000", conversions=10, revenue="600"),), terms=(), objective="sales"
        )
    )
    signals = _technical()
    technical = evaluate_technical_health(42, signals, generated_at=NOW)

    constraints = council_constraints([], technical, signals, now=NOW, finances=snapshot)

    [entry] = constraints.imposed
    assert entry.decision == (
        "a oprit automat creșterea bugetului în tura de noapte: venitul atribuit nu acoperă "
        "cheltuiala cu reclamele (ROAS 0,60)"
    )
    assert constraints.spend_freeze is not None
    assert constraints.spend_freeze.code == CFO_NIGHT_CODE


def test_a_cut_that_costs_no_money_restricts_nothing(session: Session) -> None:
    account = _client_account(session)
    _remember(session, account, "cfo", "a tăiat oprirea reclamei «X»", "loser", days_ago=1)

    assert "council" not in run_propose_job(client_account_id=account.id or 0)


# --- memoria: consiliul scrie codurile, jobul le citeste ----------------------------------


class _Memory:
    def __init__(self) -> None:
        self.written: list[Any] = []

    def recall(self, client_account_id: int, limit: int = 5) -> list[Any]:
        return []

    def remember(self, client_account_id: int, entries: Any) -> None:
        self.written.extend(entries)


def test_the_council_writes_machine_codes_that_the_night_job_reads(session: Session) -> None:
    account = _client_account(session)
    memory = _Memory()
    council = QueenCouncil(
        _Static(LOSING),
        technical=_StaticTechnical(_technical(BROKEN_TAG, evidence=GA4_DOWN)),
        memory=memory,
        clock=lambda: NOW,
    )

    council.evaluate_client_query("Merită să cresc bugetul?", _directive())

    codes = {entry.role: entry.code for entry in memory.written}
    assert codes["cto"] == "ATTRIBUTION_BROKEN"
    assert codes["cfo"] == "budget"

    DbMemory(session).remember(account.id or 0, memory.written)
    decisions = DbMemory(session).decisions(account.id or 0, NOW - timedelta(days=7))
    assert {(entry.role, entry.code) for entry in decisions} == {
        ("cto", "ATTRIBUTION_BROKEN"),
        ("cfo", "budget"),
    }


def test_the_night_runs_the_e2e_test_before_the_proposals(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _client_account(session)
    order: list[str] = []
    for name in (
        "run_metrics_sync_job",
        "run_speed_check_job",
        "run_tracking_contract_job",
        "run_propose_job",
        "run_fatigue_check_job",
    ):
        monkeypatch.setattr(
            tasks_module, name, lambda *, client_account_id, _name=name: order.append(_name) or {}
        )

    tasks_module.run_client_maintenance_job(client_account_id=account.id or 0)

    assert order.index("run_tracking_contract_job") < order.index("run_propose_job")
    assert order.index("run_speed_check_job") < order.index("run_propose_job")


# --- ce vede clientul ---------------------------------------------------------------------


def test_the_client_sees_why_a_proposal_was_blocked_and_cannot_approve_it(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],  # noqa: F811
    session: Session,
) -> None:
    client, _, headers, account_id = signed_in
    account = session.get(ClientAccount, account_id)
    assert account is not None
    _remember(session, account, "cto", PIXEL_VETO, "ATTRIBUTION_BROKEN", days_ago=1)
    launch = _launch(session, account)

    run_propose_job(client_account_id=account_id)

    response = client.get("/api/v1/proposals/blocked", headers=headers)
    assert response.status_code == 200, response.text
    blocked = response.json()
    assert blocked and all(item["status"] == "blocked" for item in blocked)
    assert launch.id in {item["id"] for item in blocked}
    assert all(item["error_message"].startswith("Oprită de consiliu.") for item in blocked)
    pending = client.get("/api/v1/proposals/pending", headers=headers).json()
    assert launch.id not in {item["id"] for item in pending}

    approve = client.post(f"/api/v1/proposals/{launch.id}/approve", headers=headers)
    assert approve.status_code == 409
