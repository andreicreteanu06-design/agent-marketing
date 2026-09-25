"""Regina in serverul real: semnalele din DB si propunerile de rescriere ale PPC-ului.

Invariantele importante sunt tot negative, ca la evaluatorul autonom: Regina nu
scrie nimic, PPC-ul scrie doar propuneri ``pending``, o rescriere nu muta bani
si nu se poate executa automat, iar o eroare a Reginei nu opreste Kelly/Thompson.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlmodel import Session, select

from ppc_agent.services.execution_engine import NoExecutorError, execute_proposal, resolve_target
from ppc_agent_server.jobs import tasks as tasks_module
from ppc_agent_server.jobs.brand_alignment import (
    RESOURCE_TYPE,
    SOURCE_MODULE,
    apply_brand_directive,
)
from ppc_agent_server.jobs.tasks import run_propose_job
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdPerformanceRecord,
    AdQueueItem,
    AdQueueStatus,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    Platform,
    ProposedChange,
    SearchTermConversion,
    SubscriptionStatus,
    Tenant,
)
from ppc_agent_server.services.queen_agent import BrandStrategist, SearchSignal
from ppc_agent_server.services.queen_signals import (
    DbBrandSignals,
    SearchConsoleIntent,
    load_live_ads,
)

TECHNICAL_HEADLINE = "Schimb ulei ATF cutie automata"
TECHNICAL_TEXT = (
    "Procedura dinamica cu aparat dedicat, ulei ATF Dexron VI si filtru OEM. "
    "Specificatii la cerere."
)


class _FakeSeoIntent:
    """Search Console conectat, cu cautarile unui service de cutii automate."""

    def __init__(self, queries: list[SearchSignal] | None = None) -> None:
        self._queries = queries if queries is not None else [
            SearchSignal("programare service cutie automata", "organic", 900, 40),
            SearchSignal("service cutie automata deschis sambata", "organic", 400, 22),
            SearchSignal("schimb ulei cutie automata langa mine", "organic", 650, 30),
            SearchSignal("schimb ulei cutie automata pret", "organic", 700, 25),
        ]

    def queries(self, account: ClientAccount) -> tuple[list[SearchSignal], list[str]]:
        return list(self._queries), []


@pytest.fixture
def account(session: Session) -> ClientAccount:
    tenant = Tenant(name="Agentie", api_key_hash="k", subscription_status=SubscriptionStatus.ACTIVE)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    client_account = ClientAccount(
        tenant_id=tenant.id,  # type: ignore[arg-type]
        name="Service Cutii",
        target_domain="autofix.ro",
        brand_name="autofix",
    )
    session.add(client_account)
    session.commit()
    session.refresh(client_account)
    return client_account


def _seed_paid_terms(session: Session, account_id: int) -> None:
    now = datetime.now(tz=UTC)
    rows = [
        ("programare online schimb ulei cutie automata", 250, 30, 7.0),
        ("programare online schimb ulei cutie automata", 250, 30, 7.0),
        ("service cutie automata pret", 420, 45, 3.0),
        ("cum schimbi singur uleiul la cutia automata", 380, 35, 0.0),
    ]
    for day_offset, (term, impressions, clicks, conversions) in enumerate(rows, start=1):
        session.add(
            SearchTermConversion(
                client_account_id=account_id,
                day=now - timedelta(days=day_offset),
                search_term=term,
                impressions=impressions,
                clicks=clicks,
                cost=Decimal("100"),
                conversions=conversions,
            )
        )
    # In afara ferestrei de 30 de zile - nu trebuie sa conteze.
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=now - timedelta(days=90),
            search_term="service cutie automata non stop",
            impressions=9000,
            clicks=900,
            cost=Decimal("5000"),
            conversions=50.0,
        )
    )
    session.commit()


def _seed_meta_launch(
    session: Session, account_id: int, *, ad_id: str = "120001", headline: str = TECHNICAL_HEADLINE
) -> None:
    """O campanie Meta lansata prin aprobare: textul in ``after``, ``ad_id`` in rezultat."""
    session.add(
        ProposedChange(
            client_account_id=account_id,
            op=ChangeOp.CREATE_CAMPAIGN,
            resource="meta_ad_account/act_1",
            resource_type="ad_account",
            after={"headline": headline, "primary_text": TECHNICAL_TEXT},
            projected_daily_spend=Decimal("30"),
            rationale="lansare",
            source_module="campaign_launch",
            status=ChangeStatus.EXECUTED,
            execution_result={"campaign_id": "c1", "adset_id": "s1", "ad_id": ad_id},
        )
    )
    session.add(
        AdPerformanceRecord(
            client_account_id=account_id,
            ad_id=ad_id,
            platform=AdFatiguePlatform.META,
            launch_time=datetime.now(tz=UTC) - timedelta(days=20),
            spend=Decimal("620"),
            target_cpa=Decimal("80"),
            conversions=9,
        )
    )
    session.commit()


def _seed_queue_copy(
    session: Session, account_id: int, *, status: AdQueueStatus = AdQueueStatus.APPROVED
) -> AdQueueItem:
    item = AdQueueItem(
        client_account_id=account_id,
        platform=Platform.GOOGLE,
        target_keyword="programare service",
        emotion_trigger="economie de timp",
        product_usp="programare online",
        ad_copy={
            "headline_1": "Programare online în 2 minute",
            "headline_2": "Gata în aceeași zi",
            "description": "Ne ocupăm noi de tot, fără cozi și fără bătăi de cap.",
        },
        status=status,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _queen(session: Session, seo: _FakeSeoIntent | None = None) -> BrandStrategist:
    return BrandStrategist(DbBrandSignals(session, seo_intent=seo or _FakeSeoIntent()))


def _queen_proposals(session: Session, account_id: int) -> list[ProposedChange]:
    return list(
        session.exec(
            select(ProposedChange)
            .where(ProposedChange.client_account_id == account_id)
            .where(ProposedChange.source_module == SOURCE_MODULE)
        ).all()
    )


# --- semnalele din DB -----------------------------------------------------------


def test_db_signals_gather_paid_terms_ads_and_brand(
    session: Session, account: ClientAccount
) -> None:
    _seed_paid_terms(session, account.id or 0)
    _seed_meta_launch(session, account.id or 0)
    _seed_queue_copy(session, account.id or 0)
    _seed_queue_copy(session, account.id or 0, status=AdQueueStatus.PENDING_REVIEW)

    signals = DbBrandSignals(session, seo_intent=_FakeSeoIntent()).load(account.id or 0)

    assert signals.brand == "autofix"
    paid = {s.query: s for s in signals.searches if s.origin == "paid"}
    # Agregat pe termen, doar in fereastra: randul de acum 90 de zile lipseste.
    assert set(paid) == {
        "programare online schimb ulei cutie automata",
        "service cutie automata pret",
        "cum schimbi singur uleiul la cutia automata",
    }
    assert paid["programare online schimb ulei cutie automata"].conversions == 14.0
    assert paid["programare online schimb ulei cutie automata"].impressions == 500
    assert sum(s.origin == "organic" for s in signals.searches) == 4

    refs = [ad.ref for ad in signals.ads]
    assert refs[0] == "meta_ad/120001"
    assert len(refs) == 2  # copy-ul inca in revizuire nu ruleaza
    meta = signals.ads[0]
    assert meta.headline == TECHNICAL_HEADLINE
    assert meta.cpa == Decimal("68.89")
    assert meta.target_cpa == Decimal("80")


def test_paused_ads_are_not_live(session: Session, account: ClientAccount) -> None:
    _seed_meta_launch(session, account.id or 0)
    session.add(
        ProposedChange(
            client_account_id=account.id or 0,
            op=ChangeOp.PAUSE,
            resource="meta_ad/120001",
            resource_type="ad",
            rationale="oboseala",
            source_module="fatigue_monitor",
            status=ChangeStatus.EXECUTED,
        )
    )
    session.commit()
    assert load_live_ads(session, account.id or 0) == []


def test_search_console_demo_data_never_reaches_the_queen(account: ClientAccount) -> None:
    """Fara Search Console conectat, pagina arata date demo - Regina nu le foloseste."""
    queries, notes = SearchConsoleIntent().queries(account)
    assert queries == []
    assert notes and "nu folosește datele demonstrative" in notes[0]


# --- propunerile PPC din directiva ------------------------------------------------


def test_misaligned_ad_becomes_a_pending_rewrite(session: Session, account: ClientAccount) -> None:
    _seed_paid_terms(session, account.id or 0)
    _seed_meta_launch(session, account.id or 0)
    _seed_queue_copy(session, account.id or 0)

    summary = apply_brand_directive(session, account.id or 0, strategist=_queen(session))

    assert summary["status"] == "ok"
    assert summary["avatar"] == "Ocupatul pragmatic"
    assert summary["misaligned"] == 1
    assert summary["proposed"] == 1
    [proposal] = _queen_proposals(session, account.id or 0)
    assert proposal.op == ChangeOp.UPDATE
    assert proposal.status == ChangeStatus.PENDING
    assert proposal.resource == "meta_ad/120001"
    assert proposal.resource_type == RESOURCE_TYPE
    assert proposal.projected_daily_spend == Decimal("0")
    assert proposal.before["headline"] == TECHNICAL_HEADLINE
    assert proposal.before["cpa"] == "68.89"
    assert proposal.after["emotion_trigger"] == "economie de timp"
    assert proposal.after["copy_brief"].startswith("Schimbă textele din tehnice")
    assert "pare stabilă" in proposal.rationale


def test_rewrite_is_not_proposed_twice(session: Session, account: ClientAccount) -> None:
    _seed_paid_terms(session, account.id or 0)
    _seed_meta_launch(session, account.id or 0)

    apply_brand_directive(session, account.id or 0, strategist=_queen(session))
    second = apply_brand_directive(session, account.id or 0, strategist=_queen(session))

    assert second["proposed"] == 0
    assert second["skipped_duplicates"] == 1
    assert len(_queen_proposals(session, account.id or 0)) == 1


def test_no_rewrites_without_enough_data(session: Session, account: ClientAccount) -> None:
    _seed_meta_launch(session, account.id or 0)

    summary = apply_brand_directive(
        session, account.id or 0, strategist=_queen(session, _FakeSeoIntent([]))
    )

    assert summary["status"] == "insufficient_data"
    assert summary["proposed"] == 0
    assert _queen_proposals(session, account.id or 0) == []


def test_approved_rewrite_is_never_executed_automatically(
    session: Session, account: ClientAccount
) -> None:
    """Nu exista executor pentru text: motorul refuza explicit, omul aplica manual."""
    _seed_paid_terms(session, account.id or 0)
    _seed_meta_launch(session, account.id or 0)
    apply_brand_directive(session, account.id or 0, strategist=_queen(session))
    [proposal] = _queen_proposals(session, account.id or 0)

    target = resolve_target(proposal)
    assert (target.platform, target.kind) == ("meta", "ad")
    with pytest.raises(NoExecutorError, match="se aplica manual"):
        execute_proposal(proposal, object(), current_status="pending")  # type: ignore[arg-type]

    queue_rewrite = ProposedChange(
        client_account_id=account.id or 0,
        op=ChangeOp.UPDATE,
        resource="ad_queue_item/7",
        resource_type=RESOURCE_TYPE,
        rationale="x",
        source_module=SOURCE_MODULE,
    )
    with pytest.raises(NoExecutorError, match="manual"):
        resolve_target(queue_rewrite)


# --- jobul de noapte: Regina inainte de Kelly/Thompson ----------------------------


def test_propose_job_consults_the_queen_before_kelly_thompson(
    session: Session, account: ClientAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_queen = tasks_module.apply_brand_directive
    real_plan = tasks_module.run_plan

    def _queen_step(session_: Session, client_account_id: int) -> dict[str, Any]:
        order.append("regina")
        return real_queen(session_, client_account_id, strategist=_queen(session_))

    def _plan(*args: Any, **kwargs: Any) -> Any:
        order.append("kelly_thompson")
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(tasks_module, "apply_brand_directive", _queen_step)
    monkeypatch.setattr(tasks_module, "run_plan", _plan)
    _seed_paid_terms(session, account.id or 0)
    _seed_meta_launch(session, account.id or 0)

    result = run_propose_job(client_account_id=account.id or 0)

    assert order == ["regina", "kelly_thompson"]
    assert result["brand_alignment"]["proposed"] == 1
    assert result["created"] > 0  # propunerile de buget au mers mai departe
    assert len(_queen_proposals(session, account.id or 0)) == 1


def test_queen_failure_does_not_block_the_ppc(
    session: Session, account: ClientAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(session_: Session, client_account_id: int) -> dict[str, Any]:
        raise RuntimeError("Search Console a picat")

    monkeypatch.setattr(tasks_module, "apply_brand_directive", _boom)

    result = run_propose_job(client_account_id=account.id or 0)

    assert "RuntimeError" in result["brand_alignment"]["error"]
    assert result["created"] > 0
