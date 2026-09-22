"""Evaluatorul autonom: ce propune, ce NU face, si cum se inlantuie.

Invariantul cel mai important e negativ: job-ul nu atinge niciun cont de
reclame. Se testeaza direct - numarand randurile scrise si starea lor.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlmodel import Session, select

from ppc_agent.search_data.serp_tracker import OpenSerpProvider
from ppc_agent_server.jobs import serp_sync
from ppc_agent_server.jobs.autonomous_evaluator import (
    RESOURCE_TYPE,
    SOURCE_MODULE,
    run_autonomous_evaluations,
)
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    SearchTermConversion,
    SerpPosition,
    SerpSource,
    SubscriptionStatus,
    Tenant,
    TrackedKeyword,
)


@pytest.fixture
def account(session: Session) -> ClientAccount:
    tenant = Tenant(name="Agentie", api_key_hash="k", subscription_status=SubscriptionStatus.ACTIVE)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    client_account = ClientAccount(
        tenant_id=tenant.id, name="Client Auto", target_domain="exemplu.ro"
    )
    session.add(client_account)
    session.commit()
    session.refresh(client_account)
    return client_account


def _seed_cannibalized(session: Session, account_id: int, term: str = "service auto") -> None:
    """Un termen pe pozitia 1 organic, pe care se cheltuie in continuare."""
    now = datetime.now(tz=UTC)
    session.add(
        SerpPosition(
            client_account_id=account_id,
            checked_on=now,
            keyword=term,
            domain="exemplu.ro",
            source=SerpSource.OPENSERP,
            rank=1.0,
        )
    )
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=now - timedelta(days=1),
            search_term=term,
            clicks=80,
            cost=Decimal("1500.00"),
            conversions=25.0,
            conversions_value=Decimal("6000"),
        )
    )
    session.commit()


def _proposals(session: Session, account_id: int) -> list[ProposedChange]:
    return list(
        session.exec(
            select(ProposedChange).where(ProposedChange.client_account_id == account_id)
        ).all()
    )


def test_canibalizarea_devine_propunere_in_asteptare(
    account: ClientAccount, session: Session
) -> None:
    _seed_cannibalized(session, account.id or 0)
    result = asyncio.run(run_autonomous_evaluations(client_account_id=account.id))

    assert result["proposals_created"] == 1
    assert result["applied_changes"] == 0

    (change,) = _proposals(session, account.id or 0)
    assert change.status is ChangeStatus.PENDING
    assert change.op is ChangeOp.PAUSE
    assert change.resource == "service auto"
    assert change.resource_type == RESOURCE_TYPE
    assert change.source_module == SOURCE_MODULE
    # Dupa pauza resursa nu mai cheltuie nimic; ce se opreste ramane in `before`.
    assert change.projected_daily_spend == Decimal("0")
    assert change.before["paid_cost"] == "1500.00"


def test_rationale_contine_cifrele_pe_care_omul_ia_decizia(
    account: ClientAccount, session: Session
) -> None:
    _seed_cannibalized(session, account.id or 0)
    asyncio.run(run_autonomous_evaluations(client_account_id=account.id))
    (change,) = _proposals(session, account.id or 0)

    assert "service auto" in change.rationale
    assert "1500.00" in change.rationale
    # Onestitatea cifrei face parte din contract, nu e ornament.
    assert "LIMITA SUPERIOARA" in change.rationale


def test_nu_propune_de_doua_ori_acelasi_termen(
    account: ClientAccount, session: Session
) -> None:
    """Fara asta, un job zilnic ar umple coada de aprobari cu acelasi rand."""
    _seed_cannibalized(session, account.id or 0)
    asyncio.run(run_autonomous_evaluations(client_account_id=account.id))
    second = asyncio.run(run_autonomous_evaluations(client_account_id=account.id))

    assert second["proposals_created"] == 0
    assert len(_proposals(session, account.id or 0)) == 1


def test_un_termen_pe_care_nu_ranchezi_nu_produce_propunere(
    account: ClientAccount, session: Session
) -> None:
    now = datetime.now(tz=UTC)
    session.add(
        SerpPosition(
            client_account_id=account.id or 0,
            checked_on=now,
            keyword="cizme dama",
            domain="exemplu.ro",
            source=SerpSource.OPENSERP,
            rank=24.0,
        )
    )
    session.add(
        SearchTermConversion(
            client_account_id=account.id or 0,
            day=now - timedelta(days=1),
            search_term="cizme dama",
            clicks=10,
            cost=Decimal("200"),
            conversions=4.0,
            conversions_value=Decimal("800"),
        )
    )
    session.commit()

    result = asyncio.run(run_autonomous_evaluations(client_account_id=account.id))
    assert result["proposals_created"] == 0


def test_clientii_agentiilor_suspendate_sunt_sariti(
    account: ClientAccount, session: Session
) -> None:
    """Nu are cine sa aprobe propunerile unui cont suspendat."""
    tenant = session.get(Tenant, account.tenant_id)
    assert tenant is not None
    tenant.subscription_status = SubscriptionStatus.SUSPENDED
    session.add(tenant)
    session.commit()
    _seed_cannibalized(session, account.id or 0)

    result = asyncio.run(run_autonomous_evaluations())
    assert result["clients_evaluated"] == 0
    assert _proposals(session, account.id or 0) == []


# --- inlantuirea dupa sincronizare ------------------------------------------


def _provider(handler: object) -> OpenSerpProvider:
    return OpenSerpProvider(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_sincronizarea_reusita_declanseaza_evaluarea(
    account: ClientAccount, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = account.id or 0
    session.add(TrackedKeyword(client_account_id=account_id, keyword="service auto"))
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=datetime.now(tz=UTC) - timedelta(days=1),
            search_term="service auto",
            clicks=80,
            cost=Decimal("1500.00"),
            conversions=25.0,
            conversions_value=Decimal("6000"),
        )
    )
    session.commit()

    monkeypatch.setattr(
        serp_sync,
        "_build_provider",
        lambda settings: _provider(
            lambda request: httpx.Response(
                200, json=[{"type": "organic", "url": "https://exemplu.ro/p"}]
            )
        ),
    )
    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)

    assert result["saved"] == 1
    assert result["evaluation"]["proposals_created"] == 1
    assert len(_proposals(session, account_id)) == 1


def test_sincronizarea_blocata_nu_declanseaza_evaluarea(
    account: ClientAccount, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pe pozitii partiale, o evaluare ar propune pauze pornind de la jumatate de tablou."""
    account_id = account.id or 0
    session.add(TrackedKeyword(client_account_id=account_id, keyword="service auto"))
    session.commit()
    _seed_cannibalized(session, account_id)

    monkeypatch.setattr(
        serp_sync,
        "_build_provider",
        lambda settings: _provider(
            lambda request: httpx.Response(200, text="detected unusual traffic")
        ),
    )
    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)

    assert result["halted"] == "blocked"
    assert "evaluation" not in result
    assert _proposals(session, account_id) == []
