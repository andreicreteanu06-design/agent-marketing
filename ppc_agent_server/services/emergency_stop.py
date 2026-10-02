"""Oprirea de urgenta: un admin opreste din chat tot ce cheltuie platforma.

Cine: doar emailurile din ``ADMIN_EMAILS`` (``routers/queen.py`` recunoaste comanda).
Ce face, in ordine:

1. scrie oprirea (``EmergencyStop``) - de acum, nicio propunere care cheltuie nu se mai
   depune, aproba sau executa, iar jobul de noapte nu mai propune (:func:`require_running`);
2. opreste (``BLOCKED``) toate propunerile in asteptare care ar cheltui - pauzele raman,
   ele doar scad cheltuiala;
3. pune pe pauza in Meta fiecare campanie lansata de platforma (``CREATE_CAMPAIGN``
   executat), pe contul ei.

Reluarea ridica doar blocajul: campaniile raman pe pauza pana le pornesti manual din Ads
Manager - ca la lansare, nimic nu incepe sa cheltuie fara un om.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, col, select

from ppc_agent.config import ProviderMode
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    EmergencyStop,
    ProposedChange,
)

logger = logging.getLogger("ppc_agent_server.services.emergency_stop")

#: Ce cheltuie (la fel ca ``execution_engine._SPENDING_OPS``); pauzele nu.
SPENDING_OPS = frozenset({ChangeOp.CREATE, ChangeOp.UPDATE, ChangeOp.CREATE_CAMPAIGN})
STOPPED_MESSAGE = (
    "Platforma e oprită de urgență de un administrator: nicio cheltuială nouă până la reluare."
)


@dataclass
class StopReport:
    """Ce a facut oprirea - raspunsul din chat."""

    already_stopped: bool = False
    blocked_proposals: int = 0
    paused: list[str] = field(default_factory=list)
    #: Campaniile care n-au putut fi oprite, cu motivul - de oprit manual din Ads Manager.
    failed: list[str] = field(default_factory=list)


def active_stop(session: Session) -> EmergencyStop | None:
    return session.exec(
        select(EmergencyStop).where(col(EmergencyStop.resumed_at).is_(None))
    ).first()


def require_running(session: Session) -> None:
    """Pentru orice drum care ar cheltui: 423 cat timp oprirea e activa."""
    if active_stop(session) is not None:
        raise HTTPException(status_code=423, detail=STOPPED_MESSAGE)


def _pause_launched(session: Session, report: StopReport) -> None:
    launched = session.exec(
        select(ProposedChange)
        .where(ProposedChange.op == ChangeOp.CREATE_CAMPAIGN)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
    ).all()
    for proposal in launched:
        campaign_id = (proposal.execution_result or {}).get("campaign_id")
        if not campaign_id:
            continue
        account = session.get(ClientAccount, proposal.client_account_id)
        config = _app_config_for(account) if account is not None else None
        if config is None or config.provider_mode is not ProviderMode.LIVE:
            report.failed.append(f"{campaign_id}: contul nu e în modul live")
            continue
        provider = ProviderFactory(config).meta_mutations()
        if provider is None:
            report.failed.append(f"{campaign_id}: contul Meta nu e conectat")
            continue
        try:
            asyncio.run(provider.pause_campaign(campaign_id))
        except Exception as exc:  # o campanie care nu se opreste nu le opreste pe celelalte
            logger.critical(
                "oprirea de urgenta n-a oprit campania %s: %r", campaign_id, exc,
                extra={"event": "emergency_pause_failed", "campaign_id": campaign_id},
            )
            report.failed.append(f"{campaign_id}: {type(exc).__name__}")
        else:
            report.paused.append(campaign_id)


def stop_all(session: Session, *, by: str) -> StopReport:
    """Oprirea de urgenta (idempotenta: a doua oara doar mai incearca pauzele)."""
    report = StopReport(already_stopped=active_stop(session) is not None)
    now = datetime.now(tz=UTC)
    if not report.already_stopped:
        session.add(EmergencyStop(stopped_at=now, stopped_by=by))
        session.commit()
    result = session.exec(
        update(ProposedChange)
        .where(col(ProposedChange.status) == ChangeStatus.PENDING)
        .where(col(ProposedChange.op).in_(SPENDING_OPS))
        .values(
            status=ChangeStatus.BLOCKED,
            decided_at=now,
            decided_by=by,
            error_message=STOPPED_MESSAGE,
        )
    )
    session.commit()
    report.blocked_proposals = result.rowcount
    _pause_launched(session, report)
    logger.critical(
        "oprire de urgenta data de %s: %d propuneri oprite, %d campanii pe pauza, %d esuate",
        by, report.blocked_proposals, len(report.paused), len(report.failed),
        extra={"event": "emergency_stop", "by": by},
    )
    return report


def resume(session: Session, *, by: str) -> bool:
    """Ridica oprirea; ``False`` daca nu era activa. Campaniile raman pe pauza."""
    stop = active_stop(session)
    if stop is None:
        return False
    stop.resumed_at = datetime.now(tz=UTC)
    stop.resumed_by = by
    session.add(stop)
    session.commit()
    logger.warning("oprirea de urgenta ridicata de %s", by, extra={"event": "emergency_resume"})
    return True
