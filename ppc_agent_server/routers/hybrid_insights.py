"""Motorul hibrid PPC+SEO expus catre site: cuvinte urmarite si analize incrucisate.

Autentificare prin token de CLIENT (acelasi JWT ca restul zonei ``/cont`` -
vezi ``routers/client_auth.py``), nu prin cheia de agentie: datele astea sunt
ale clientului si se vad din interfata lui.

Cele doua analize sunt motivul pentru care exista tot lantul: un tool de SEO
are index, dar nu stie cat platesti si ce converteste; un tool de PPC stie
cheltuiala, dar nu stie unde ranchezi. Aici sunt amandoua.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ppc_agent.search_data.insights import (
    TOP_ORGANIC_POSITION,
    WEAK_ORGANIC_POSITION,
    CannibalizationDetector,
    SeoOpportunityFinder,
)
from ppc_agent_server.db import get_session
from ppc_agent_server.hybrid_queries import (
    DEFAULT_WINDOW_DAYS,
    load_latest_positions,
    load_organic_positions,
    load_paid_terms,
)
from ppc_agent_server.models import ClientUser, TrackedKeyword
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import (
    CannibalizationItem,
    CannibalizationReport,
    SeoOpportunityItem,
    SeoOpportunityReport,
    TrackedKeywordCreate,
    TrackedKeywordRow,
)

router = APIRouter(prefix="/api/v1/hybrid", tags=["hybrid"])

_ZERO = Decimal("0")

WindowDays = Annotated[
    int, Query(ge=1, le=365, description="Fereastra de analiza, in zile.")
]


def _client_account_id(client_user: ClientUser) -> int:
    """ID-ul contului clientului autentificat."""
    return client_user.client_account_id


@router.post("/keywords", response_model=TrackedKeywordRow, status_code=201)
def add_tracked_keyword(
    payload: TrackedKeywordCreate,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> TrackedKeywordRow:
    """Adauga un cuvant de urmarit organic.

    Idempotent pe (client, cuvant): re-adaugarea unui cuvant existent il
    REACTIVEAZA in loc sa creeze un duplicat, fiindca altfel istoricul lui s-ar
    rupe in doua siruri care arata la fel.
    """
    account_id = _client_account_id(client_user)
    keyword = payload.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="cuvantul cheie nu poate fi gol")

    existing = session.exec(
        select(TrackedKeyword)
        .where(TrackedKeyword.client_account_id == account_id)
        .where(TrackedKeyword.keyword == keyword)
    ).first()
    if existing is not None:
        existing.is_active = True
        existing.intent = payload.intent
        if payload.target_url:
            existing.target_url = payload.target_url
        tracked = existing
    else:
        tracked = TrackedKeyword(
            client_account_id=account_id,
            keyword=keyword,
            intent=payload.intent,
            target_url=payload.target_url,
        )
        session.add(tracked)

    session.commit()
    session.refresh(tracked)
    return TrackedKeywordRow(
        id=tracked.id or 0,
        keyword=tracked.keyword,
        intent=tracked.intent,
        target_url=tracked.target_url,
        is_active=tracked.is_active,
    )


@router.get("/keywords", response_model=list[TrackedKeywordRow])
def list_tracked_keywords(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    days: WindowDays = DEFAULT_WINDOW_DAYS,
) -> list[TrackedKeywordRow]:
    """Cuvintele urmarite, cu ultima pozitie si cu ce fac ele in reclame.

    Cele doua laturi se aduc separat si se imbina pe cuvantul normalizat:
    pozitia vine din istoricul de SERP, cheltuiala si conversiile din raportul
    de termeni de cautare. Un cuvant poate avea una fara cealalta - ambele
    cazuri sunt informatie, nu lipsa de date.
    """
    account_id = _client_account_id(client_user)
    tracked = list(
        session.exec(
            select(TrackedKeyword)
            .where(TrackedKeyword.client_account_id == account_id)
            .order_by(TrackedKeyword.keyword)
        ).all()
    )
    positions = load_latest_positions(session, account_id)
    paid_by_term = {
        term.term.strip().lower(): term
        for term in load_paid_terms(session, account_id, days=days)
    }

    rows: list[TrackedKeywordRow] = []
    for item in tracked:
        key = item.keyword.strip().lower()
        position = positions.get(key)
        paid = paid_by_term.get(key)
        rows.append(
            TrackedKeywordRow(
                id=item.id or 0,
                keyword=item.keyword,
                intent=item.intent,
                target_url=item.target_url,
                is_active=item.is_active,
                latest_rank=position.rank if position else None,
                latest_rank_source=position.source if position else None,
                latest_checked_on=position.checked_on if position else None,
                ranking_url=position.page_url if position else "",
                paid_clicks=paid.clicks if paid else None,
                paid_cost=paid.cost if paid else None,
                paid_conversions=paid.conversions if paid else None,
                paid_cpa=paid.cpa if paid else None,
            )
        )
    return rows


@router.get("/insights/cannibalization", response_model=CannibalizationReport)
def get_cannibalization(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    days: WindowDays = DEFAULT_WINDOW_DAYS,
) -> CannibalizationReport:
    """Termeni pe care ii detinem deja in top organic, dar pentru care platim.

    NU spune "taie bugetul": incrementalitatea reclamei se masoara cu un test,
    nu se presupune. Spune "aici merita testata o oprire", cu suma la vedere.
    """
    account_id = _client_account_id(client_user)
    findings = CannibalizationDetector().find(
        load_paid_terms(session, account_id, days=days),
        load_organic_positions(session, account_id),
    )
    return CannibalizationReport(
        window_days=days,
        top_position_threshold=TOP_ORGANIC_POSITION,
        total_potential_saving=sum(
            (item.potential_monthly_saving for item in findings), start=_ZERO
        ),
        items=[
            CannibalizationItem(
                term=item.term,
                organic_position=item.organic_position,
                paid_clicks=item.paid_clicks,
                paid_cost=item.paid_cost,
                paid_conversions=item.paid_conversions,
                potential_saving=item.potential_monthly_saving,
            )
            for item in findings
        ],
    )


@router.get("/insights/opportunities", response_model=SeoOpportunityReport)
def get_opportunities(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    days: WindowDays = DEFAULT_WINDOW_DAYS,
) -> SeoOpportunityReport:
    """Termeni care CONVERTESC platit, dar unde organic lipsim (pozitie >10 sau deloc).

    Sortati dupa conversii, nu dupa volum estimat: un cuvant cu 40.000 de
    cautari si zero conversii nu merita un articol, unul cu 90 si 12 merita.
    """
    account_id = _client_account_id(client_user)
    opportunities = SeoOpportunityFinder().find(
        load_paid_terms(session, account_id, days=days),
        load_organic_positions(session, account_id),
    )
    return SeoOpportunityReport(
        window_days=days,
        weak_position_threshold=WEAK_ORGANIC_POSITION,
        items=[
            SeoOpportunityItem(
                term=item.term,
                paid_conversions=item.paid_conversions,
                paid_cost=item.paid_cost,
                paid_cpa=item.paid_cpa,
                roas=item.roas,
                organic_position=item.organic_position,
            )
            for item in opportunities
        ],
    )
