"""Construieste ``ClientReport`` dintr-un ``ClientAccount`` - agrega
``AdPerformanceRecord`` + ``ProposedChange`` intr-un rezumat in limbaj simplu,
fara jargon tehnic (Gate B, Thompson Sampling etc.), gata de aratat unui client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent.decision.budget_strategy import recommend_arm_capacity
from ppc_agent.errors import BudgetAllocationError
from ppc_agent_server.models import AdPerformanceRecord, ClientAccount, ProposedChange
from ppc_agent_server.reporting.models import AdReportLine, ClientReport, DecisionNarrative

_MAX_DECISIONS = 15

_FATIGUE_EXPLANATIONS: dict[str, str] = {
    "PAUSE_HARD": "nu a adus nicio conversie, desi a cheltuit peste pragul acceptat",
    "PAUSE_PROVISIONAL": "rata de click a fost mult sub media contului",
    "PAUSE_REPLACE": "interesul publicului a scazut clar (oboseala creativa)",
}


def _narrative_for(change: ProposedChange) -> str | None:
    """Traduce o propunere in limbaj simplu, sau ``None`` daca nu merita aratata
    unui client (ex. cuvinte cheie negative - prea granulare, vezi apelantul)."""
    resource_name = change.resource.split("/", 1)[-1]

    if change.source_module == "fatigue_monitor":
        verdict = change.after.get("verdict") if isinstance(change.after, dict) else None
        reason = _FATIGUE_EXPLANATIONS.get(
            str(verdict), "performanta a scazut sub pragul acceptabil"
        )
        return f'Anuntul "{resource_name}" a fost oprit - {reason}.'

    if change.source_module == "budget":
        if change.projected_daily_spend == 0:
            return (
                f'Bugetul pentru "{resource_name}" a fost redus la zero - alte '
                "campanii aveau sanse mai mari de reusita."
            )
        return (
            f'Bugetul pentru "{resource_name}" a fost ajustat la '
            f"{change.projected_daily_spend} lei/zi, pe baza performantei recente."
        )

    if change.source_module == "meta_liquidity":
        return (
            "Seturile de reclame Meta cu volum mic au fost consolidate, ca sa "
            "iasa mai repede din faza de invatare a algoritmului."
        )

    return None  # "negatives" si orice modul necunoscut - prea granular pentru client


def _capacity_note(account: ClientAccount) -> str | None:
    """Nota despre cate variante active poate sustine bugetul curent, sau
    ``None`` daca bugetul/valoarea proxy nu sunt (inca) valide pentru calcul."""
    try:
        advice = recommend_arm_capacity(account.max_daily_spend, account.default_lead_value)
    except BudgetAllocationError:
        return None
    return advice.rationale


def build_client_report(session: Session, account: ClientAccount) -> ClientReport:
    """Agrega starea curenta a unui client intr-un raport prezentabil.

    Args:
        session: Sesiunea DB activa.
        account: Clientul deja validat fata de agentia autentificata (vezi
            ``deps.get_owned_client``).

    Returns:
        Raportul complet: totaluri, performanta per anunt, decizii recente de
        optimizare (in limbaj simplu) si o nota despre capacitatea bugetului.
    """
    records = session.exec(
        select(AdPerformanceRecord).where(AdPerformanceRecord.client_account_id == account.id)
    ).all()

    ads = [
        AdReportLine(
            ad_id=record.ad_id,
            platform=record.platform.value,
            status=record.status.value,
            spend=record.spend,
            revenue=record.revenue,
            conversions=record.conversions,
            roas=record.roas,
        )
        for record in records
    ]
    total_spend = sum((record.spend for record in records), Decimal("0"))
    total_revenue = sum((record.revenue for record in records), Decimal("0"))
    total_conversions = sum(record.conversions for record in records)
    roas = float(total_revenue / total_spend) if total_spend > 0 else 0.0

    changes = session.exec(
        select(ProposedChange)
        .where(ProposedChange.client_account_id == account.id)
        .order_by(ProposedChange.created_at.desc())  # type: ignore[attr-defined]
    ).all()

    decisions: list[DecisionNarrative] = []
    excluded_negatives = 0
    for change in changes:
        if change.source_module == "negatives":
            excluded_negatives += 1
            continue
        text = _narrative_for(change)
        if text is None:
            continue
        decisions.append(
            DecisionNarrative(when=change.created_at, text=text, status=change.status.value)
        )
        if len(decisions) >= _MAX_DECISIONS:
            break

    return ClientReport(
        client_name=account.name,
        objective=account.objective,
        generated_at=datetime.now(tz=UTC),
        daily_budget=account.max_daily_spend,
        total_spend=total_spend,
        total_revenue=total_revenue,
        roas=roas,
        total_conversions=total_conversions,
        ads=ads,
        decisions=decisions,
        capacity_note=_capacity_note(account),
        excluded_negative_keywords=excluded_negatives,
    )
