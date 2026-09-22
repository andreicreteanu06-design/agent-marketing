"""Interogarile care aduc datele hibride PPC+SEO din DB in forma analizelor.

Stau separat de router deliberat: analizele din ``ppc_agent/search_data/insights.py``
sunt functii pure peste ``PaidSearchTerm``/``OrganicPosition``, iar modulul asta
e singurul loc care stie cum se ajunge de la randuri SQL la acele forme. Asa
raman ambele testabile - una fara DB, cealalta fara HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent.search_data.insights import OrganicPosition, PaidSearchTerm
from ppc_agent_server.models import SearchTermConversion, SerpPosition, SerpSource

#: Fereastra implicita de analiza. 30 de zile: destul cat sa se adune conversii,
#: destul de recent cat sa reflecte contul de azi, nu de acum un trimestru.
DEFAULT_WINDOW_DAYS = 30


@dataclass(slots=True)
class _Accumulator:
    """Totalurile unui termen peste fereastra. ``Decimal`` pentru bani, nu float."""

    clicks: int = 0
    cost: Decimal = Decimal("0")
    conversions: float = 0.0
    value: Decimal = Decimal("0")


def window_start(days: int = DEFAULT_WINDOW_DAYS) -> datetime:
    return datetime.now(tz=UTC) - timedelta(days=days)


def load_paid_terms(
    session: Session, client_account_id: int, *, days: int = DEFAULT_WINDOW_DAYS
) -> list[PaidSearchTerm]:
    """Termenii de cautare platiti, AGREGATI pe termen peste fereastra ceruta.

    Agregarea se face aici, nu in SQL, fiindca ``cost``/``conversions_value``
    sunt ``Decimal`` si vrem adunarea exacta - un ``SUM()`` peste SQLite le-ar
    intoarce ca float si ar introduce erori de rotunjire in cifre de bani.
    """
    rows = session.exec(
        select(SearchTermConversion)
        .where(SearchTermConversion.client_account_id == client_account_id)
        .where(SearchTermConversion.day >= window_start(days))
    ).all()

    totals: dict[str, _Accumulator] = {}
    for row in rows:
        bucket = totals.setdefault(row.search_term, _Accumulator())
        bucket.clicks += row.clicks
        bucket.cost += row.cost
        bucket.conversions += row.conversions
        bucket.value += row.conversions_value

    return [
        PaidSearchTerm(
            term=term,
            clicks=data.clicks,
            cost=data.cost,
            conversions=data.conversions,
            conversions_value=data.value,
        )
        for term, data in totals.items()
    ]


def load_latest_positions(
    session: Session, client_account_id: int, *, source: SerpSource | None = None
) -> dict[str, SerpPosition]:
    """Cea mai recenta pozitie per cuvant, optional filtrata pe sursa.

    Cheia e cuvantul in litere mici: cele doua surse (Search Console si
    OpenSERP) scriu aceeasi interogare cu capitalizari diferite, iar o
    potrivire sensibila la litere ar produce doua randuri pentru acelasi cuvant.
    """
    statement = select(SerpPosition).where(
        SerpPosition.client_account_id == client_account_id
    )
    if source is not None:
        statement = statement.where(SerpPosition.source == source)

    latest: dict[str, SerpPosition] = {}
    for row in session.exec(statement.order_by(SerpPosition.checked_on)).all():  # type: ignore[arg-type]
        # Ordonat crescator, deci ultimul scris pentru o cheie e cel mai recent.
        latest[row.keyword.strip().lower()] = row
    return latest


def load_organic_positions(
    session: Session, client_account_id: int
) -> list[OrganicPosition]:
    """Pozitiile organice curente, in forma ceruta de analize.

    Foloseste orice sursa disponibila: Search Console e preferabila (pozitie
    masurata pe trafic real), dar pentru cuvintele pe care nu aparem inca acolo
    singura cifra existenta vine din OpenSERP. Randurile fara ``rank``
    ("am verificat, nu apare") sunt omise intentionat - a le trata ca pozitia 0
    ar fi o minciuna, iar analizele le trateaza corect ca absente.
    """
    return [
        OrganicPosition(
            query=row.keyword,
            position=float(row.rank),
            clicks=row.clicks or 0,
            impressions=row.impressions or 0,
        )
        for row in load_latest_positions(session, client_account_id).values()
        if row.rank is not None
    ]
