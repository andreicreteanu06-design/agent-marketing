"""Scara de evenimente si garda fazei de invatare, de la ordine pana la jobul de noapte."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlmodel import Session, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.decision.learning_guard import LearningState
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.services.execution_engine import LearningPhaseHold, execute_proposal
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ConversionEvent,
    ConversionEventType,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.services.campaign_orders import optimization_event
from ppc_agent_server.services.optimization_upgrade import propose_upgrades
from tests_server.test_proposal_execution import _CAP, _FakeMetaProvider, _proposal

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


# --- scara de evenimente ---------------------------------------------------------


@pytest.mark.parametrize(
    ("budget", "cpa", "event"),
    [
        ("100", "10", "SUBMIT_APPLICATION"),  # 70 pe saptamana
        ("50", "7", "SUBMIT_APPLICATION"),  # exact 50: pragul trece
        ("49", "7", "LEAD"),  # 49: sub prag
        ("25", "35", "LEAD"),  # 5 pe saptamana
    ],
)
def test_scara_alege_evenimentul_dupa_volumul_saptamanal(budget: str, cpa: str, event: str) -> None:
    chosen, weekly, _ = optimization_event(
        CampaignObjective.LEAD_GEN, daily_budget=Decimal(budget), target_cpa=Decimal(cpa)
    )
    assert chosen == event
    assert weekly == pytest.approx(float(Decimal(budget) * 7 / Decimal(cpa)))


def test_fara_cpa_tinta_scara_porneste_pe_lead() -> None:
    chosen, weekly, reason = optimization_event(
        CampaignObjective.LEAD_GEN, daily_budget=Decimal("500"), target_cpa=None
    )
    assert (chosen, weekly) == ("LEAD", None)
    assert "necunoscut" in reason


def test_vanzarile_optimizeaza_mereu_pe_achizitie() -> None:
    chosen, _, _ = optimization_event(
        CampaignObjective.SALES, daily_budget=Decimal("5"), target_cpa=Decimal("100")
    )
    assert chosen == "PURCHASE"


# --- garda la executie --------------------------------------------------------------


class _LearningMeta(_FakeMetaProvider):
    def __init__(self, state: LearningState | None, current_budget: Decimal) -> None:
        super().__init__(current_budget=current_budget)
        self.state = state

    async def learning_state(self, adset_id: str) -> LearningState | None:  # type: ignore[override]
        return self.state


def _learning(days: float = 1) -> LearningState:
    return LearningState(status="LEARNING", since=datetime.now(tz=UTC) - timedelta(days=days))


def test_o_crestere_mare_de_buget_in_invatare_se_amana() -> None:
    provider = _LearningMeta(_learning(), current_budget=Decimal("50"))
    proposal = _proposal(op=ChangeOp.UPDATE, spend="100")

    with pytest.raises(LearningPhaseHold, match="ramane in asteptare"):
        execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert provider.budgets == []


def test_o_ajustare_mica_de_buget_trece_si_in_invatare() -> None:
    provider = _LearningMeta(_learning(), current_budget=Decimal("50"))
    proposal = _proposal(op=ChangeOp.UPDATE, spend="55")

    result = execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)

    assert result.executed
    assert provider.budgets == [("23848", Decimal("55"))]


def test_learning_limited_cu_cpa_la_tinta_lasa_bugetul_sa_creasca() -> None:
    state = LearningState(
        status="FAIL", since=datetime.now(tz=UTC), spend=Decimal("200"), conversions=10
    )
    provider = _LearningMeta(state, current_budget=Decimal("50"))
    proposal = _proposal(op=ChangeOp.UPDATE, spend="100")

    result = execute_proposal(
        proposal,
        provider,
        current_status="pending",
        max_daily_spend=_CAP,
        target_cpa=Decimal("25"),
    )
    assert result.executed


def test_pauza_nu_e_oprita_niciodata_de_garda() -> None:
    provider = _LearningMeta(_learning(), current_budget=Decimal("50"))
    result = execute_proposal(_proposal(), provider, current_status="pending", max_daily_spend=_CAP)
    assert result.executed and provider.paused_adsets == ["23848"]


# --- citirea starii din Meta ----------------------------------------------------------


def test_providerul_live_citeste_invatarea_si_cpa_ul_ultimelor_7_zile() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "learning_stage_info": {"status": "LEARNING", "last_sig_edit_ts": 1_760_000_000},
                "created_time": "2026-10-01T10:00:00+0000",
                "insights": {
                    "data": [
                        {"spend": "120.50", "actions": [{"action_type": "lead", "value": "5"}]}
                    ]
                },
            },
        )

    provider = LiveMetaMarketingProvider(access_token="t", transport=httpx.MockTransport(handler))
    state = asyncio.run(provider.learning_state("adset_1"))

    assert state is not None
    assert state.status == "LEARNING"
    assert state.since == datetime.fromtimestamp(1_760_000_000, tz=UTC)
    assert state.spend == Decimal("120.50")
    assert "learning_stage_info" in seen[0]


# --- upgrade-ul de noapte ---------------------------------------------------------------


def _account(session: Session) -> ClientAccount:
    tenant = Tenant(name="Agentie", api_key_hash="x" * 64)
    session.add(tenant)
    session.commit()
    account = ClientAccount(
        tenant_id=tenant.id or 0,
        name="Clinica",
        objective=CampaignObjective.LEAD_GEN,
        default_lead_value=Decimal("40"),
    )
    session.add(account)
    session.commit()
    return account


def _lead_launch(session: Session, account: ClientAccount, event: str = "LEAD") -> None:
    session.add(
        ProposedChange(
            client_account_id=account.id or 0,
            op=ChangeOp.CREATE_CAMPAIGN,
            resource="meta_ad_account/act_1",
            resource_type="campaign",
            after={"custom_event_type": event},
            projected_daily_spend=Decimal("100"),
            rationale="lansare",
            source_module="campaigns",
            status=ChangeStatus.EXECUTED,
            execution_result={"adset_id": "as_1", "ad_id": "ad_1", "extra_ad_ids": "ad_2"},
        )
    )
    session.commit()


def _leads(session: Session, account: ClientAccount, per_week: tuple[int, int]) -> None:
    for week, count in enumerate(per_week):
        for index in range(count):
            session.add(
                ConversionEvent(
                    client_account_id=account.id or 0,
                    event_id=f"w{week}_{index}",
                    event_type=ConversionEventType.LEAD,
                    source_platform="custom_web",
                    ad_id="ad_1" if index % 2 else "ad_2",
                    qualified=True,
                    created_at=NOW - timedelta(days=7 * week + 1),
                )
            )
    session.commit()


def _upgrades(session: Session) -> list[ProposedChange]:
    return list(
        session.exec(
            select(ProposedChange).where(ProposedChange.resource_type == "optimization_event")
        ).all()
    )


def test_doua_saptamani_peste_50_aduc_propunerea_de_upgrade(session: Session) -> None:
    account = _account(session)
    _lead_launch(session, account)
    _leads(session, account, (60, 52))

    result = propose_upgrades(session, account, learning=lambda _: None, now=NOW)

    assert result["proposed"] == ["as_1"]
    [upgrade] = _upgrades(session)
    assert upgrade.status is ChangeStatus.PENDING
    assert upgrade.resource == "meta_optimization/as_1"
    assert upgrade.after["custom_event_type"] == "SUBMIT_APPLICATION"
    assert upgrade.before["weekly_qualified_leads"] == [60, 52]
    assert "Upgrade optimizare" in upgrade.rationale

    again = propose_upgrades(session, account, learning=lambda _: None, now=NOW)
    assert again["proposed"] == [] and len(_upgrades(session)) == 1


def test_o_saptamana_buna_nu_e_stabilitate(session: Session) -> None:
    account = _account(session)
    _lead_launch(session, account)
    _leads(session, account, (70, 30))

    result = propose_upgrades(session, account, learning=lambda _: None, now=NOW)
    assert result["proposed"] == [] and "volum insuficient" in result["skipped"]["as_1"]


def test_upgrade_ul_se_amana_cat_timp_ad_set_ul_invata(session: Session) -> None:
    account = _account(session)
    _lead_launch(session, account)
    _leads(session, account, (60, 60))
    learning = LearningState(status="LEARNING", since=NOW - timedelta(days=2))

    result = propose_upgrades(session, account, learning=lambda _: learning, now=NOW)
    assert result["proposed"] == [] and "reporni invatarea" in result["skipped"]["as_1"]


def test_o_campanie_deja_pe_lead_calificat_nu_primeste_upgrade(session: Session) -> None:
    account = _account(session)
    _lead_launch(session, account, event="SUBMIT_APPLICATION")
    _leads(session, account, (60, 60))

    assert propose_upgrades(session, account, learning=lambda _: None, now=NOW)["proposed"] == []
