"""Teste pentru record_conversion() si to_ad_performance_state() (fara HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.decision.fatigue_monitor import evaluate_ad
from ppc_agent.providers.live.meta import AdDay, AdInsight
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdLifecycleStatus,
    AdPerformanceRecord,
    ClientAccount,
    ConversionEvent,
    Tenant,
)
from ppc_agent_server.tracking.models import StandardizedConversion
from ppc_agent_server.tracking.pipeline import (
    apply_platform_insight,
    record_conversion,
    to_ad_performance_state,
)


def _client_account(
    session: Session,
    *,
    default_lead_value: str = "300.00",
    objective: CampaignObjective = CampaignObjective.LEAD_GEN,
) -> ClientAccount:
    tenant = Tenant(name="Agentie Test", api_key_hash="hash")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    account = ClientAccount(
        tenant_id=tenant.id,  # type: ignore[arg-type]
        name="Client Test",
        default_lead_value=Decimal(default_lead_value),
        objective=objective,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_record_conversion_persists_event_with_hashed_pii(session: Session) -> None:
    account = _client_account(session)
    conversion = StandardizedConversion(
        event_id="e1",
        event_type="purchase",
        value=199.99,
        client_id=str(account.id),
        source_platform="gomag",
        customer_email="Test@Exemplu.ro",
        customer_phone="0712345678",
    )
    outcome = record_conversion(session, account, conversion)
    assert outcome.qualified
    assert not outcome.deduplicated

    event = session.exec(select(ConversionEvent).where(ConversionEvent.event_id == "e1")).one()
    assert event.email_sha256 is not None
    assert event.phone_sha256 is not None
    assert "Test@Exemplu.ro" not in (event.email_sha256 or "")
    assert event.qualified is True


def test_record_conversion_deduplicates_by_event_id(session: Session) -> None:
    account = _client_account(session)
    conversion = StandardizedConversion(
        event_id="dup-1", client_id=str(account.id), source_platform="custom_web", value=10.0
    )
    first = record_conversion(session, account, conversion)
    second = record_conversion(session, account, conversion)

    assert not first.deduplicated
    assert second.deduplicated
    assert second.qualified == first.qualified

    all_events = session.exec(
        select(ConversionEvent).where(ConversionEvent.event_id == "dup-1")
    ).all()
    assert len(all_events) == 1  # nu s-a inserat de doua ori


def test_record_conversion_unqualified_call_does_not_touch_ad_record(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="tt_infeed",
        platform=AdFatiguePlatform.TIKTOK,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=100),
        target_cpa=Decimal("10.00"),
    )
    session.add(record)
    session.commit()

    conversion = StandardizedConversion(
        event_id="short-call",
        event_type="phone_call",
        call_duration_seconds=15,  # sub minimul de 60s
        client_id=str(account.id),
        source_platform="call_tracker",
        ad_id="tt_infeed",
    )
    outcome = record_conversion(session, account, conversion)
    assert not outcome.qualified

    session.refresh(record)
    assert record.conversions == 0
    assert record.revenue == Decimal("0")


def test_record_conversion_qualified_lead_increments_existing_ad_record(
    session: Session,
) -> None:
    account = _client_account(session, default_lead_value="250.00")
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_brand",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=100),
        target_cpa=Decimal("10.00"),
        conversions=2,
        revenue=Decimal("100.00"),
    )
    session.add(record)
    session.commit()

    conversion = StandardizedConversion(
        event_id="lead-1",
        event_type="lead",
        value=None,  # -> primeste valoarea proxy a contului (250.00)
        client_id=str(account.id),
        source_platform="custom_web",
        ad_id="c_brand",
    )
    outcome = record_conversion(session, account, conversion)
    assert outcome.qualified

    session.refresh(record)
    assert record.conversions == 3
    assert record.revenue == Decimal("350.00")


def test_record_conversion_creates_new_ad_record_when_ad_platform_known(
    session: Session,
) -> None:
    account = _client_account(session)
    conversion = StandardizedConversion(
        event_id="new-ad-1",
        event_type="purchase",
        value=500.0,
        client_id=str(account.id),
        source_platform="gomag",
        ad_id="tt_new_ad",
        ad_platform="tiktok",
    )
    record_conversion(session, account, conversion)

    record = session.exec(
        select(AdPerformanceRecord).where(AdPerformanceRecord.ad_id == "tt_new_ad")
    ).one()
    assert record.platform == AdFatiguePlatform.TIKTOK
    assert record.status == AdLifecycleStatus.NEW
    assert record.conversions == 1
    assert record.revenue == Decimal("500.0")
    assert record.target_cpa == account.default_lead_value


def test_record_conversion_without_ad_id_or_platform_skips_ad_record(
    session: Session,
) -> None:
    account = _client_account(session)
    conversion = StandardizedConversion(
        event_id="organic-1",
        event_type="contact",
        client_id=str(account.id),
        source_platform="custom_web",
    )
    outcome = record_conversion(session, account, conversion)
    assert outcome.qualified

    assert session.exec(select(AdPerformanceRecord)).first() is None


def test_to_ad_performance_state_round_trips_into_evaluate_ad(session: Session) -> None:
    """Podul catre evaluate_ad() functioneaza cu date reale dintr-un rand persistat.

    Trece prin add/commit/refresh (nu doar construieste obiectul in memorie) -
    persistarea reala e ceea ce a scos la iveala bug-ul de fus orar de mai jos.
    """
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_dying",
        platform=AdFatiguePlatform.GOOGLE,
        status=AdLifecycleStatus.NEW,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=72),
        spend=Decimal("25.00"),
        target_cpa=Decimal("10.00"),
        conversions=0,
        impressions=1600,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    state = to_ad_performance_state(record)
    assert state.ad_id == "c_dying"
    assert state.platform == "google"
    assert evaluate_ad(state, datetime.now(tz=UTC)) == "PAUSE_HARD"


def test_to_ad_performance_state_normalizes_naive_datetime_from_sqlite(
    session: Session,
) -> None:
    """SQLite intoarce launch_time fara tzinfo - evaluate_ad tot trebuie sa functioneze.

    Regresie: gasita prin verificare live (uvicorn), nu de testele initiale -
    niciunul nu facea round-trip complet prin sesiune inainte de evaluate_ad.
    """
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_naive",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=200),
        target_cpa=Decimal("10.00"),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    assert record.launch_time.tzinfo is None  # confirma reproducerea bug-ului

    state = to_ad_performance_state(record)
    assert state.launch_time.tzinfo is not None
    assert evaluate_ad(state, datetime.now(tz=UTC)) == "CONTINUE"  # nu ridica TypeError


def test_sales_account_purchase_without_value_leaves_revenue_at_zero(
    session: Session,
) -> None:
    """SALES: ROAS trebuie sa vina din valoarea dinamica a webhook-ului - o
    conversie fara valoare NU primeste proxy, deci nu umfla artificial venitul."""
    account = _client_account(session, objective=CampaignObjective.SALES)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="ecom_ad",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=100),
        target_cpa=Decimal("50.00"),
    )
    session.add(record)
    session.commit()

    conversion = StandardizedConversion(
        event_id="sale-no-value",
        event_type="purchase",
        value=None,
        client_id=str(account.id),
        source_platform="gomag",
        ad_id="ecom_ad",
    )
    outcome = record_conversion(session, account, conversion)
    assert outcome.qualified

    session.refresh(record)
    assert record.conversions == 1
    assert record.revenue == Decimal("0")  # fara proxy - nu s-a "inventat" venit


def test_lead_gen_account_purchase_typed_event_still_gets_proxy_value(
    session: Session,
) -> None:
    """Obiectivul contului guverneaza, nu tipul evenimentului - chiar si un
    eveniment "purchase" fara valoare primeste proxy pe un cont LEAD_GEN."""
    account = _client_account(
        session, default_lead_value="220.00", objective=CampaignObjective.LEAD_GEN
    )
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="lead_ad",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=100),
        target_cpa=Decimal("50.00"),
    )
    session.add(record)
    session.commit()

    conversion = StandardizedConversion(
        event_id="lead-gen-purchase-event",
        event_type="purchase",
        value=None,
        client_id=str(account.id),
        source_platform="custom_web",
        ad_id="lead_ad",
    )
    record_conversion(session, account, conversion)

    session.refresh(record)
    assert record.revenue == Decimal("220.00")


_NOW = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)


def _days(*spec: tuple[int, float, int, int, float]) -> tuple[AdDay, ...]:
    """(acum cate zile, cheltuiala, afisari, click-uri, conversii) -> zile incheiate."""
    yesterday = _NOW.date() - timedelta(days=1)
    return tuple(
        AdDay(day=yesterday - timedelta(days=ago), spend=spend, impressions=shown,
              clicks=clicks, conversions=sold)
        for ago, spend, shown, clicks, sold in sorted(spec, reverse=True)
    )


def _meta_record() -> AdPerformanceRecord:
    return AdPerformanceRecord(
        client_account_id=1,
        ad_id="a1",
        platform=AdFatiguePlatform.META,
        launch_time=_NOW,
        target_cpa=Decimal("300"),
    )


def test_a_tired_winner_is_replaced_but_one_still_under_target_is_left_alone() -> None:
    """Poarta C primea doar zerouri: starea nu trecea niciodata pe "profitable"."""
    good = [(ago, 50.0, 2000, 40, 1.0) for ago in range(3, 14)]  # CPA 50, CTR 2%
    tired = [(ago, 80.0, 2000, 20, 1.0) for ago in range(3)]  # CPA 80, CTR 1%
    insight = AdInsight(
        ad_id="a1", name="Video", created_time=_NOW - timedelta(days=30), active=True,
        spend=1200.0, impressions=40000, clicks=700, conversions=30.0, revenue=3000.0,
        frequency_7d=3.5, days=_days(*good, *tired),
    )

    record = _meta_record()
    apply_platform_insight(
        record, insight, target_cpa=Decimal("60"), account_median_ctr=0.02, now=_NOW
    )
    assert record.status is AdLifecycleStatus.PROFITABLE  # CPA 40 de la lansare, tinta 60
    assert record.bad_days_last_5 == 3  # ultimele 3 zile, peste tinta
    assert evaluate_ad(to_ad_performance_state(record), _NOW) == "PAUSE_REPLACE"

    # Aceeasi tendinta, dar zilele raman sub tinta (300): reclama inca aduce bani.
    cheap = _meta_record()
    apply_platform_insight(
        cheap, insight, target_cpa=Decimal("300"), account_median_ctr=0.02, now=_NOW
    )
    assert cheap.bad_days_last_5 == 0
    assert evaluate_ad(to_ad_performance_state(cheap), _NOW) == "CONTINUE"


def test_an_ad_that_no_longer_runs_is_not_judged() -> None:
    record = _meta_record()
    stopped = AdInsight(ad_id="a1", name="Oprit", created_time=_NOW, active=False)
    apply_platform_insight(
        record, stopped, target_cpa=Decimal("300"), account_median_ctr=0.0, now=_NOW
    )
    assert record.status is AdLifecycleStatus.PAUSED
    assert evaluate_ad(to_ad_performance_state(record), _NOW + timedelta(days=9)) == "CONTINUE"
