"""Raportul saptamanal: generat per client, salvat in ``WeeklyReport``.

Legatura dintre straturile din ``ppc_agent/services/reporting`` si baza de date.
Aici, si numai aici, se citesc deciziile executate - stratul RAW nu importa
serverul - si se salveaza payload-ul. Un raport pe saptamana si client:
regenerarea il inlocuieste, nu il dubleaza.

Rezumatul executiv se cere modelului de limbaj doar in modul ``live``. In modul
``mock`` n-ar avea ce spune in plus fata de cifre, iar un text "AI" scris din
date inventate ar fi exact ce raportul incearca sa evite.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.config import ProviderMode
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.services.reporting.extractors import (
    ReportWindow,
    extract_decisions,
    extract_platform_daily,
)
from ppc_agent.services.reporting.serving import build_weekly_report
from ppc_agent_server.db import get_engine
from ppc_agent_server.jobs.autonomous_evaluator import ACTIVE_STATUSES
from ppc_agent_server.jobs.tasks import _app_config_for, _require_client
from ppc_agent_server.models import (
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    Tenant,
    WeeklyReport,
)

logger = logging.getLogger("ppc_agent_server.jobs.weekly_report")


def window_for(week_end: date | None) -> ReportWindow:
    """Saptamana care se termina la ``week_end``, sau ultima saptamana incheiata."""
    if week_end is not None:
        return ReportWindow.ending(week_end)
    return ReportWindow.last_complete_week(datetime.now(tz=UTC).date())


def generate_weekly_report(
    session: Session, account: ClientAccount, window: ReportWindow
) -> WeeklyReport:
    """Genereaza raportul lui ``account`` pentru ``window`` si il salveaza.

    Returns:
        Randul salvat - nou, sau cel existent pentru aceeasi saptamana, inlocuit.
    """
    config = _app_config_for(account)
    extract = extract_platform_daily(
        ProviderFactory(config),
        accounts={
            "google_ads": config.settings.google_ads_customer_id,
            "meta_ads": config.settings.meta_ad_account_id,
        },
        window=window,
    )
    # Filtrarea pe fereastra se face in Python (extract_decisions): SQLite
    # intoarce datele fara fus orar, iar o comparatie in SQL cu o data cu fus
    # orar ar compara siruri. Volumul - propunerile executate ale unui client -
    # e mic.
    executed = session.exec(
        select(ProposedChange)
        .where(ProposedChange.client_account_id == account.id)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
    ).all()
    summarizer = (
        CreativeFactory(config).llm() if config.provider_mode is ProviderMode.LIVE else None
    )
    payload = build_weekly_report(
        client_account_id=account.id or 0,
        # O singura moneda pe raport: Google Ads si Meta se presupun in aceeasi
        # moneda a contului (PPC_META_CURRENCY). Sume in monede diferite nu se
        # aduna.
        currency=config.settings.meta_currency,
        window=window,
        extract=extract,
        decisions=extract_decisions(executed, window),
        summarizer=summarizer,
        track_roas=account.objective is CampaignObjective.SALES,
    )

    report = session.exec(
        select(WeeklyReport)
        .where(WeeklyReport.client_account_id == account.id)
        .where(WeeklyReport.week_start == window.start)
    ).first() or WeeklyReport(
        client_account_id=account.id or 0, week_start=window.start, week_end=window.end
    )
    report.week_end = window.end
    report.generated_at = payload.generated_at
    report.payload = payload.model_dump(mode="json")
    session.add(report)
    session.commit()
    session.refresh(report)
    logger.info(
        "raport saptamanal %s - %s pentru %s: %d goluri de date, rezumat %s",
        window.start,
        window.end,
        account.name,
        len(payload.data_gaps),
        payload.summary_source,
    )
    return report


def run_weekly_report_job(
    *, client_account_id: int, week_end: date | None = None
) -> dict[str, Any]:
    """Job: raportul unui singur client."""
    window = window_for(week_end)
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        report = generate_weekly_report(session, account, window)
        return {
            "weekly_report_id": report.id,
            "week_start": window.start.isoformat(),
            "week_end": window.end.isoformat(),
            "summary_source": report.payload.get("summary_source"),
            "data_gaps": len(report.payload.get("data_gaps", [])),
        }


def run_weekly_reports_job(*, week_end: date | None = None) -> dict[str, Any]:
    """Job: rapoartele tuturor clientilor agentiilor active (cron-ul de luni).

    Un client stricat nu opreste restul: eroarea lui se raporteaza, ceilalti
    continua - la fel ca evaluatorul de noapte.
    """
    window = window_for(week_end)
    results: dict[str, Any] = {}
    with Session(get_engine()) as session:
        accounts = list(
            session.exec(
                select(ClientAccount)
                .join(Tenant)
                .where(Tenant.subscription_status.in_(ACTIVE_STATUSES))  # type: ignore[attr-defined]
            ).all()
        )
        for account in accounts:
            try:
                report = generate_weekly_report(session, account, window)
            except Exception as exc:
                session.rollback()
                logger.warning(
                    "raport saptamanal esuat pentru %s: %s: %s",
                    account.name,
                    type(exc).__name__,
                    exc,
                )
                results[str(account.id)] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            results[str(account.id)] = {"weekly_report_id": report.id}
    return {
        "week_start": window.start.isoformat(),
        "week_end": window.end.isoformat(),
        "clients": len(accounts),
        "results": results,
    }
