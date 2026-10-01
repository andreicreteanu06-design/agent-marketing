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
from ppc_agent_server.models import ChangeStatus, ClientAccount, ProposedChange
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
    """Suma bugetelor zilnice ale propunerilor executate sau in curs de aplicare.

    Include si campaniile lansate OPRITE: activarea lor din Ads Manager nu mai
    trece prin noi, deci bugetul lor e angajat din momentul crearii.

    Insumarea se face in Python, pe ``Decimal`` - nu cu ``SUM()`` in SQL, care
    pe SQLite ar trece prin float. ``exclude_id``: propunerea care se verifica
    chiar acum, deja rezervata - nu se numara de doua ori. ``client_account_id``
    ``None``: toata platforma.
    """
    query = select(ProposedChange).where(col(ProposedChange.status).in_(_COMMITTED))
    if client_account_id is not None:
        query = query.where(ProposedChange.client_account_id == client_account_id)
    if exclude_id is not None:
        query = query.where(ProposedChange.id != exclude_id)
    committed = session.exec(query).all()
    return sum((change.projected_daily_spend for change in committed), Decimal("0"))


def check_spend_limit(
    session: Session,
    account: ClientAccount,
    additional: Decimal,
    *,
    exclude_id: int | None = None,
) -> None:
    """Refuza orice ar duce angajamentul total peste plafonul clientului sau al platformei.

    Verifica TOTALUL, nu doar suma noua: altfel N aprobari individuale, fiecare
    sub plafon, l-ar putea depasi impreuna.

    ``additional <= 0`` (o pauza, o reducere) trece mereu: oprirea cheltuielii
    nu trebuie blocata tocmai cand angajamentul e deja peste plafon.

    Raises:
        SpendLimitExceeded: un plafon ar fi depasit (-> 409), cu alerta CRITICAL.
    """
    if additional <= 0:
        return
    global_cap = get_server_settings().max_daily_spend_ron
    checks = (
        ("client", account.max_daily_spend, account.id or 0),
        ("platforma", global_cap, None),
    )
    for scope, cap, account_filter in checks:
        total = committed_daily_spend(session, account_filter, exclude_id=exclude_id) + additional
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
