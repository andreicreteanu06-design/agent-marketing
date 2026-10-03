"""Plafonul absolut de cheltuiala, verificat pe TOT ce s-a angajat deja.

Folosit de fiecare ruta care poate duce la cheltuiala noua - aprobarea unei
propuneri si propunerea unei lansari. Un singur loc, ca doua rute sa nu poata
aduna diferit acelasi angajament.

Doua plafoane, amandoua pe angajamentul TOTAL:

- al clientului (``ClientAccount.max_daily_spend``);
- al platformei (``MAX_DAILY_SPEND_RON``): suma pe TOTI clientii. Scutul
  pilotului - oricat ar permite limitele individuale, platforma nu angajeaza
  mai mult de atat pe zi.

Un refuz e o alerta CRITICAL in log: ceva (un om, un job, o propunere) a
incercat sa treaca de plafon.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlmodel import Session, col, select

from ppc_agent.errors import SpendLimitExceeded
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent_server.models import ChangeOp, ChangeStatus, ClientAccount, ProposedChange
from ppc_agent_server.settings import get_server_settings

logger = logging.getLogger("ppc_agent_server.spend_guard")

#: Starile care au angajat bani: executate, si - cat timp cererea catre platforma
#: e in zbor - rezervate (``APPROVED``, vezi ``routers/proposals.py``). Fara ele,
#: doua propuneri aprobate in aceeasi secunda ar trece fiecare de plafon, dar
#: impreuna l-ar depasi.
_COMMITTED = (ChangeStatus.EXECUTED, ChangeStatus.APPROVED)


def committed_daily_spend(
    session: Session, client_account_id: int | None, *, exclude_id: int | None = None
) -> Decimal:
    """Bugetul zilnic angajat acum: ultimul buget executat (sau in curs) pe fiecare obiect.

    Doua schimbari pe acelasi set de reclame nu se aduna - a doua o inlocuieste pe
    prima, iar o pauza il aduce la 0. Altfel ajustarile de buget din fiecare noapte
    ar umfla angajamentul pana cand orice crestere e refuzata. Lansarile sunt
    fiecare o campanie noua, deci se aduna toate - inclusiv cele create OPRITE:
    activarea lor din Ads Manager nu mai trece prin noi.

    Insumarea se face in Python, pe ``Decimal`` - nu cu ``SUM()`` in SQL, care
    pe SQLite ar trece prin float. ``exclude_id``: propunerea care se verifica
    chiar acum, deja rezervata - nu se numara de doua ori. ``client_account_id``
    ``None``: toata platforma.
    """
    return sum(_budgets(session, client_account_id, exclude_id).values(), Decimal("0"))


def _budgets(
    session: Session, client_account_id: int | None, exclude_id: int | None
) -> dict[tuple[int, str], Decimal]:
    """Bugetul de acum, pe (client, obiect); o lansare e cheia ei proprie."""
    query = select(ProposedChange).where(col(ProposedChange.status).in_(_COMMITTED))
    if client_account_id is not None:
        query = query.where(ProposedChange.client_account_id == client_account_id)
    if exclude_id is not None:
        query = query.where(ProposedChange.id != exclude_id)
    budgets: dict[tuple[int, str], Decimal] = {}
    for change in sorted(session.exec(query).all(), key=lambda row: row.id or 0):
        key = change.resource
        if change.op is ChangeOp.CREATE_CAMPAIGN:
            key = f"{key}#{change.id}"
        budgets[(change.client_account_id, key)] = change.projected_daily_spend
    return budgets


def check_spend_limit(
    session: Session,
    account: ClientAccount,
    additional: Decimal,
    *,
    exclude_id: int | None = None,
    replaces: str | None = None,
) -> None:
    """Refuza orice ar duce angajamentul total peste plafonul clientului sau al platformei.

    Verifica TOTALUL, nu doar suma noua: altfel N aprobari individuale, fiecare
    sub plafon, l-ar putea depasi impreuna.

    ``replaces``: obiectul al carui buget il inlocuieste ``additional`` (un set de
    reclame ajustat); bugetul lui de acum iese din total. O schimbare care nu
    creste cheltuiala (o pauza, o reducere) trece mereu: oprirea cheltuielii nu
    trebuie blocata tocmai cand angajamentul e deja peste plafon.

    Raises:
        SpendLimitExceeded: un plafon ar fi depasit (-> 409), cu alerta CRITICAL.
    """
    replaced = Decimal("0")
    if replaces is not None:
        budgets = _budgets(session, account.id or 0, exclude_id)
        replaced = budgets.get((account.id or 0, replaces), Decimal("0"))
    if additional <= replaced:
        return
    global_cap = get_server_settings().max_daily_spend_ron
    checks = (
        ("client", account.max_daily_spend, account.id or 0),
        ("platforma", global_cap, None),
    )
    for scope, cap, account_filter in checks:
        committed = committed_daily_spend(session, account_filter, exclude_id=exclude_id)
        total = committed - replaced + additional
        try:
            AbsoluteSpendLimiter(cap).check(total)
        except SpendLimitExceeded:
            logger.critical(
                "SPEND GUARD: plafon %s depasit - executie oprita",
                scope,
                extra={
                    "event": "spend_limit_exceeded",
                    "scope": scope,
                    "client_account_id": account.id,
                    "proposal_id": exclude_id,
                    "additional": str(additional),
                    "total": str(total),
                    "cap": str(cap),
                },
            )
            raise
