"""Plafonul absolut de cheltuiala, verificat pe TOT ce s-a angajat deja.

Folosit de fiecare ruta care poate duce la cheltuiala noua - aprobarea unei
propuneri si propunerea unei lansari. Un singur loc, ca doua rute sa nu poata
aduna diferit acelasi angajament.
"""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent_server.models import ChangeStatus, ClientAccount, ProposedChange


def committed_daily_spend(session: Session, client_account_id: int) -> Decimal:
    """Suma bugetelor zilnice ale propunerilor deja executate pentru client.

    Include si campaniile lansate OPRITE: activarea lor din Ads Manager nu mai
    trece prin noi, deci bugetul lor e angajat din momentul crearii.

    Insumarea se face in Python, pe ``Decimal`` - nu cu ``SUM()`` in SQL, care
    pe SQLite ar trece prin float.
    """
    executed = session.exec(
        select(ProposedChange).where(
            ProposedChange.client_account_id == client_account_id,
            ProposedChange.status == ChangeStatus.EXECUTED,
        )
    ).all()
    return sum((change.projected_daily_spend for change in executed), Decimal("0"))


def check_spend_limit(session: Session, account: ClientAccount, additional: Decimal) -> None:
    """Refuza orice ar duce angajamentul total peste ``max_daily_spend``.

    Verifica TOTALUL, nu doar suma noua: altfel N aprobari individuale, fiecare
    sub plafon, l-ar putea depasi impreuna.

    Raises:
        SpendLimitExceeded: plafonul ar fi depasit (-> 409).
    """
    AbsoluteSpendLimiter(account.max_daily_spend).check(
        committed_daily_spend(session, account.id or 0) + additional
    )
