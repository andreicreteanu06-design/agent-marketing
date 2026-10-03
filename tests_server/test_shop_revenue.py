"""Comenzile reale ale clientului: plafonul venitului pe care si-l atribuie platformele."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent_server.models import ClientAccount, ConversionEvent, ConversionEventType
from ppc_agent_server.tracking.pipeline import shop_revenue
from tests_server.test_jobs_tasks import _client_account

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def _event(
    session: Session,
    account: ClientAccount,
    event_id: str,
    *,
    days_ago: int,
    value: str,
    event_type: ConversionEventType = ConversionEventType.PURCHASE,
    qualified: bool = True,
) -> None:
    session.add(
        ConversionEvent(
            client_account_id=account.id or 0,
            event_id=event_id,
            event_type=event_type,
            value=Decimal(value),
            source_platform="custom_web",
            qualified=qualified,
            created_at=NOW - timedelta(days=days_ago),
        )
    )
    session.commit()


def _shop(session: Session) -> ClientAccount:
    account = _client_account(session)
    account.objective = CampaignObjective.SALES
    session.add(account)
    session.commit()
    return account


def test_orders_of_the_last_thirty_days_are_the_shop_revenue(session: Session) -> None:
    account = _shop(session)
    _event(session, account, "1", days_ago=45, value="999")  # inainte de fereastra
    _event(session, account, "2", days_ago=10, value="150")
    _event(session, account, "3", days_ago=2, value="250")
    _event(session, account, "4", days_ago=1, value="500", qualified=False)
    _event(
        session, account, "5", days_ago=1, value="300", event_type=ConversionEventType.LEAD
    )  # la un magazin, doar comenzile

    assert shop_revenue(session, account, now=NOW) == Decimal("400.00")


def test_a_webhook_younger_than_the_window_is_not_the_whole_truth(session: Session) -> None:
    """Primele comenzi au venit acum o saptamana: suma ar parea o prabusire a vanzarilor."""
    account = _shop(session)
    _event(session, account, "1", days_ago=7, value="150")

    assert shop_revenue(session, account, now=NOW) is None


def test_without_a_webhook_the_revenue_is_unknown(session: Session) -> None:
    assert shop_revenue(session, _shop(session), now=NOW) is None


def test_a_quiet_month_after_older_orders_is_zero_not_unknown(session: Session) -> None:
    account = _shop(session)
    _event(session, account, "1", days_ago=60, value="150")

    assert shop_revenue(session, account, now=NOW) == Decimal("0.00")


def test_lead_accounts_count_every_qualified_conversion(session: Session) -> None:
    account = _client_account(session)  # implicit: lead-uri
    _event(session, account, "1", days_ago=40, value="300", event_type=ConversionEventType.LEAD)
    _event(session, account, "2", days_ago=3, value="300", event_type=ConversionEventType.LEAD)
    _event(
        session, account, "3", days_ago=2, value="300",
        event_type=ConversionEventType.PHONE_CALL,
    )

    assert shop_revenue(session, account, now=NOW) == Decimal("600.00")
