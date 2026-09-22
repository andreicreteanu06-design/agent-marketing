"""Tura de noapte: evaluatorul care propune singur, dar nu aplica nimic.

Ruleaza dupa sincronizarea pozitiilor, citeste ce a iesit si transforma
canibalizarea gasita in propuneri de pus pe pauza - fiecare in starea
``pending``, adica exact acolo unde o asteapta un om.

Trei lucruri pe care le face DELIBERAT, si fara de care job-ul ar fi daunator:

1. **Nu atinge niciun cont de reclame.** Singura scriere e un rand in
   ``ProposedChange``. Nu importa niciun provider aici, deci nu exista nici
   macar calea prin care s-ar putea executa ceva din greseala.
2. **Nu propune de doua ori acelasi lucru.** Daca o propunere pentru acelasi
   termen e deja in asteptare, o sare. Fara asta, un job zilnic ar umple coada
   de aprobari cu acelasi rand de 30 de ori pe luna si ar face-o inutilizabila.
3. **Nu propune pentru clientii inactivi.** Un tenant suspendat sau anulat nu
   primeste propuneri - nu e cine sa le aprobe.

Economia din ``rationale`` e o LIMITA SUPERIOARA, nu o promisiune: o parte din
click-urile platite nu s-ar muta pe organic. Textul o spune ca atare, fiindca
omul care aproba citeste cifra aia si ia o decizie pe ea.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlmodel import Session, select

from ppc_agent.search_data.insights import CannibalizationDetector, CannibalizationFinding
from ppc_agent_server.db import get_engine
from ppc_agent_server.hybrid_queries import (
    DEFAULT_WINDOW_DAYS,
    load_organic_positions,
    load_paid_terms,
)
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    SubscriptionStatus,
    Tenant,
)

logger = logging.getLogger("ppc_agent_server.jobs.autonomous_evaluator")

SOURCE_MODULE = "autonomous_evaluator"
#: Tipul de resursa al propunerilor generate aici. Serveste si la deduplicare.
RESOURCE_TYPE = "ppc_keyword"

#: Starile de abonament pentru care are sens sa producem propuneri.
_ACTIVE_STATUSES = (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE)


def _build_rationale(finding: CannibalizationFinding) -> str:
    """Textul pe care il citeste omul care aproba. Cifre concrete, fara vorbe goale."""
    return (
        f"Termenul '{finding.term}' se claseaza organic pe pozitia "
        f"{finding.organic_position:.1f}, dar a consumat {finding.paid_cost} RON in "
        f"reclame ({finding.paid_clicks} click-uri, {finding.paid_conversions:g} conversii). "
        f"Propun pauza pe potrivirea exacta: pana la {finding.potential_monthly_saving} RON "
        "economisiti pe perioada analizata. LIMITA SUPERIOARA, nu garantie - o parte din "
        "click-uri nu se vor muta pe organic, deci trateaz-o ca test, nu ca taiere sigura."
    )


def _pending_terms(session: Session, client_account_id: int) -> set[str]:
    """Termenii pentru care exista deja o propunere in asteptare de la acest job."""
    rows = session.exec(
        select(ProposedChange.resource)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.resource_type == RESOURCE_TYPE)
        .where(ProposedChange.status == ChangeStatus.PENDING)
        .where(ProposedChange.source_module == SOURCE_MODULE)
    ).all()
    return {str(row) for row in rows}


def _to_proposal(client_account_id: int, finding: CannibalizationFinding) -> ProposedChange:
    """Propunerea de pauza pentru un termen canibalizat.

    ``projected_daily_spend`` e 0: dupa pauza, resursa nu mai cheltuie nimic.
    Cheltuiala de dinainte ramane in ``before``, ca sa se vada ce se opreste.
    """
    return ProposedChange(
        client_account_id=client_account_id,
        op=ChangeOp.PAUSE,
        resource=finding.term,
        resource_type=RESOURCE_TYPE,
        before={
            "paid_cost": str(finding.paid_cost),
            "paid_clicks": finding.paid_clicks,
            "paid_conversions": finding.paid_conversions,
            "organic_position": finding.organic_position,
        },
        after={"status": "PAUSED"},
        projected_daily_spend=Decimal("0"),
        rationale=_build_rationale(finding),
        source_module=SOURCE_MODULE,
        status=ChangeStatus.PENDING,
    )


def _evaluate_client(session: Session, account: ClientAccount, days: int) -> dict[str, Any]:
    """Evalueaza un singur client si insereaza propunerile noi."""
    account_id = account.id or 0
    findings = CannibalizationDetector().find(
        load_paid_terms(session, account_id, days=days),
        load_organic_positions(session, account_id),
    )
    if not findings:
        logger.info("[tura de noapte] %s: nicio canibalizare gasita.", account.name)
        return {"findings": 0, "proposed": 0, "skipped_duplicates": 0}

    already_pending = _pending_terms(session, account_id)
    proposed = 0
    duplicates = 0
    for finding in findings:
        if finding.term in already_pending:
            duplicates += 1
            continue
        session.add(_to_proposal(account_id, finding))
        proposed += 1
        logger.info(
            "[tura de noapte] %s: propunere PENDING pentru '%s' "
            "(organic #%.1f, %s RON cheltuiti) - asteapta aprobare umana.",
            account.name,
            finding.term,
            finding.organic_position,
            finding.paid_cost,
        )
    session.commit()

    if duplicates:
        logger.info(
            "[tura de noapte] %s: %d termeni au deja o propunere in asteptare, sariti.",
            account.name,
            duplicates,
        )
    return {"findings": len(findings), "proposed": proposed, "skipped_duplicates": duplicates}


async def run_autonomous_evaluations(
    *, client_account_id: int | None = None, days: int = DEFAULT_WINDOW_DAYS
) -> dict[str, Any]:
    """Evalueaza clientii si depune propuneri in asteptare.

    Args:
        client_account_id: doar acest client. ``None`` = toti clientii activi
            (folosit de cron-ul de noapte).
        days: fereastra de analiza.

    Returns:
        Cate propuneri s-au creat, per client. Nu ridica exceptii pentru un
        client stricat - eroarea lui se raporteaza, ceilalti continua.

    Nu face nicio cerere catre vreun API de reclame. Singura scriere e in
    ``ProposedChange``, cu ``status='pending'``.
    """
    with Session(get_engine()) as session:
        statement = select(ClientAccount).join(Tenant).where(
            Tenant.subscription_status.in_(_ACTIVE_STATUSES)  # type: ignore[attr-defined]
        )
        if client_account_id is not None:
            statement = statement.where(ClientAccount.id == client_account_id)
        accounts = list(session.exec(statement).all())

        per_client: dict[str, Any] = {}
        total_proposed = 0
        for account in accounts:
            try:
                result = _evaluate_client(session, account, days)
            except Exception as exc:
                session.rollback()
                logger.warning(
                    "[tura de noapte] %s: evaluare esuata - %s: %s",
                    account.name,
                    type(exc).__name__,
                    exc,
                )
                per_client[str(account.id)] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            per_client[str(account.id)] = result
            total_proposed += int(result["proposed"])

    logger.info(
        "[tura de noapte] gata: %d clienti evaluati, %d propuneri noi in asteptare. "
        "Nicio modificare aplicata pe conturile de reclame.",
        len(accounts),
        total_proposed,
    )
    return {
        "clients_evaluated": len(accounts),
        "proposals_created": total_proposed,
        "applied_changes": 0,
        "results": per_client,
    }
