"""Rapoartele saptamanale ale clientului - ce citeste frontend-ul din ``/cont``.

Toate rutele sunt ale clientului autentificat (JWT) si vad doar rapoartele lui.

ORDINEA DECLARARII CONTEAZA: ``/weekly/latest`` sta inaintea lui
``/weekly/{week_start}``, altfel FastAPI incearca sa citeasca "latest" ca data
si raspunde 422 - aceeasi capcana ca la ``/proposals/pending``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ppc_agent.services.reporting.serving import WeeklyReportPayload
from ppc_agent_server.db import get_session
from ppc_agent_server.jobs.weekly_report import generate_weekly_report, window_for
from ppc_agent_server.models import ClientAccount, ClientUser, WeeklyReport
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import WeeklyReportListItem

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

_NOT_FOUND = "nu exista inca un raport saptamanal pentru aceasta perioada"


def _payload(report: WeeklyReport) -> WeeklyReportPayload:
    return WeeklyReportPayload.model_validate(report.payload)


@router.get("/weekly", response_model=list[WeeklyReportListItem])
def list_weekly_reports(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[WeeklyReportListItem]:
    """Istoricul rapoartelor, cel mai recent primul."""
    reports = session.exec(
        select(WeeklyReport)
        .where(WeeklyReport.client_account_id == client_user.client_account_id)
        .order_by(WeeklyReport.week_start.desc())  # type: ignore[attr-defined]
    ).all()
    return [
        WeeklyReportListItem(
            week_start=report.week_start,
            week_end=report.week_end,
            generated_at=report.generated_at,
            summary_source=str(report.payload.get("summary_source", "template")),
        )
        for report in reports
    ]


@router.get("/weekly/latest", response_model=WeeklyReportPayload)
def latest_weekly_report(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> WeeklyReportPayload:
    """Cel mai recent raport. 404 cand nu s-a generat inca niciunul."""
    report = session.exec(
        select(WeeklyReport)
        .where(WeeklyReport.client_account_id == client_user.client_account_id)
        .order_by(WeeklyReport.week_start.desc())  # type: ignore[attr-defined]
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return _payload(report)


@router.get("/weekly/{week_start}", response_model=WeeklyReportPayload)
def weekly_report(
    week_start: date,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> WeeklyReportPayload:
    """Raportul saptamanii care incepe la ``week_start`` (``YYYY-MM-DD``)."""
    report = session.exec(
        select(WeeklyReport)
        .where(WeeklyReport.client_account_id == client_user.client_account_id)
        .where(WeeklyReport.week_start == week_start)
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return _payload(report)


@router.post("/weekly/generate", response_model=WeeklyReportPayload)
def generate_report(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    week_end: Annotated[date | None, Query()] = None,
) -> WeeklyReportPayload:
    """Genereaza (sau regenereaza) raportul unei saptamani incheiate.

    Args:
        week_end: Ultima zi a saptamanii; implicit ieri.

    Raises:
        HTTPException: 422 cand saptamana ceruta nu s-a incheiat - un raport
            pe o zi in curs ar arata cifre care inca se schimba.

    In modul ``live`` citeste Google Ads, Meta si modelul de limbaj, deci poate
    dura cateva secunde.
    """
    if week_end is not None and week_end >= datetime.now(tz=UTC).date():
        raise HTTPException(
            status_code=422,
            detail="saptamana ceruta nu s-a incheiat inca - alege o zi de pana ieri",
        )
    account = session.get(ClientAccount, client_user.client_account_id)
    if account is None:  # pragma: no cover - FK garanteaza existenta
        raise HTTPException(status_code=404, detail="contul clientului nu exista")
    return _payload(generate_weekly_report(session, account, window_for(week_end)))
