"""Upgrade de optimizare: de pe ``LEAD`` pe lead-ul calificat, cand volumul o permite.

Scara de evenimente (``campaign_orders.optimization_event``) porneste campaniile mici pe
``LEAD``, ca Meta sa iasa din invatare. Noaptea, pentru fiecare campanie lansata de
platforma pe ``LEAD``, se numara lead-urile calificate venite din reclamele ei
(``ConversionEvent`` cu ``ad_id``-ul lor). Doua saptamani la rand peste
``LEARNING_EVENTS`` = volum stabil: propunerea catre client de a trece ad set-ul pe
``SUBMIT_APPLICATION`` (lead-ul calificat, trimis doar de server), ca Meta sa invete
doar din clientii buni.

Propunerea se aplica manual in Ads Manager (fara executor, ca rescrierile de text ale
Reginei): schimbarea evenimentului reporneste invatarea, deci omul alege momentul. Nu se
propune cat timp ad set-ul invata (``decision/learning_guard.py``) si nu se repeta pentru
acelasi ad set.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, func, select

from ppc_agent.alignment.meta_liquidity import LEARNING_EVENTS
from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.decision.learning_guard import LearningState, learning_hold
from ppc_agent.providers.meta_campaign import QUALIFIED_LEAD_EVENT, STANDARD_LEAD_EVENT
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ConversionEvent,
    ConversionEventType,
    ProposedChange,
)

SOURCE_MODULE = "optimization_upgrade"
#: Fara executor (``execution_engine.resolve_target``): se aplica manual in Ads Manager.
RESOURCE_PREFIX = "meta_optimization/"
#: Cate saptamani la rand trebuie sa treaca de prag (stabilitate, nu un varf).
STABLE_WEEKS = 2
_LEAD_TYPES = (
    ConversionEventType.LEAD,
    ConversionEventType.PHONE_CALL,
    ConversionEventType.CONTACT,
)


def _lead_launches(session: Session, account_id: int) -> list[tuple[str, list[str]]]:
    """Ad set-urile lansate de platforma pe ``LEAD``, cu anunturile lor."""
    launches = session.exec(
        select(ProposedChange).where(
            ProposedChange.client_account_id == account_id,
            ProposedChange.op == ChangeOp.CREATE_CAMPAIGN,
            ProposedChange.status == ChangeStatus.EXECUTED,
        )
    ).all()
    found = []
    for launch in launches:
        created = launch.execution_result or {}
        if (launch.after or {}).get("custom_event_type") != STANDARD_LEAD_EVENT:
            continue
        if not created.get("adset_id"):
            continue
        ads = [str(created.get("ad_id", "")), *str(created.get("extra_ad_ids", "")).split(",")]
        found.append((str(created["adset_id"]), [ad for ad in ads if ad]))
    return found


def weekly_qualified_leads(
    session: Session, account_id: int, ad_ids: list[str], *, now: datetime
) -> list[int]:
    """Lead-urile calificate din anunturile date, pe saptamani (cea mai recenta prima)."""
    counts = []
    for week in range(STABLE_WEEKS):
        end = now - timedelta(days=7 * week)
        counts.append(
            session.exec(
                select(func.count())
                .select_from(ConversionEvent)
                .where(
                    ConversionEvent.client_account_id == account_id,
                    col(ConversionEvent.qualified).is_(True),
                    col(ConversionEvent.event_type).in_(_LEAD_TYPES),
                    col(ConversionEvent.ad_id).in_(ad_ids),
                    ConversionEvent.created_at >= end - timedelta(days=7),
                    ConversionEvent.created_at < end,
                )
            ).one()
        )
    return counts


def propose_upgrades(
    session: Session,
    account: ClientAccount,
    *,
    learning: Callable[[str], LearningState | None],
    now: datetime,
) -> dict[str, Any]:
    """Propunerile de upgrade pentru campaniile pe ``LEAD`` care au volum stabil.

    Args:
        learning: Starea de invatare a unui ad set (``None`` = necunoscuta).
    """
    if account.objective != CampaignObjective.LEAD_GEN:
        return {"status": "not_lead_gen"}
    proposed: list[str] = []
    skipped: dict[str, str] = {}
    for adset_id, ad_ids in _lead_launches(session, account.id or 0):
        resource = f"{RESOURCE_PREFIX}{adset_id}"
        already = session.exec(
            select(ProposedChange.id).where(
                ProposedChange.client_account_id == account.id,
                ProposedChange.resource == resource,
            )
        ).first()
        if already is not None:
            skipped[adset_id] = "upgrade deja propus"
            continue
        weekly = weekly_qualified_leads(session, account.id or 0, ad_ids, now=now)
        if min(weekly) < LEARNING_EVENTS:
            skipped[adset_id] = f"volum insuficient: {weekly} lead-uri calificate pe saptamana"
            continue
        hold = learning_hold(
            learning(adset_id), change="major", target_cpa=account.default_lead_value, now=now
        )
        if hold:
            skipped[adset_id] = hold
            continue
        session.add(_upgrade_proposal(account.id or 0, adset_id, weekly))
        proposed.append(adset_id)
    session.commit()
    return {"proposed": proposed, "skipped": skipped}


def _upgrade_proposal(account_id: int, adset_id: str, weekly: list[int]) -> ProposedChange:
    recent, previous = weekly[0], weekly[1]
    return ProposedChange(
        client_account_id=account_id,
        op=ChangeOp.UPDATE,
        resource=f"{RESOURCE_PREFIX}{adset_id}",
        resource_type="optimization_event",
        before={"custom_event_type": STANDARD_LEAD_EVENT, "weekly_qualified_leads": weekly},
        after={"custom_event_type": QUALIFIED_LEAD_EVENT, "adset_id": adset_id},
        projected_daily_spend=Decimal("0"),
        rationale=(
            f"Upgrade optimizare: campania a adus {recent} și {previous} lead-uri calificate în "
            f"ultimele două săptămâni, peste pragul de {LEARNING_EVENTS:.0f} pe săptămână. Acum "
            "există destul volum ca Meta să optimizeze pe lead-ul calificat (SubmitApplication, "
            "trimis doar de server) în loc de LEAD: învață doar din clienții buni. Schimbă "
            f"evenimentul de conversie al ad set-ului {adset_id} în Ads Manager; învățarea "
            "repornește o singură dată."
        ),
        source_module=SOURCE_MODULE,
        status=ChangeStatus.PENDING,
    )
