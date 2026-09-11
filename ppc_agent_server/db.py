"""Motorul de baze de date si sesiunile SQLModel.

Implicit SQLite local (fara nimic de instalat sau pornit — testele si dev-ul
ruleaza asa). ``DATABASE_URL`` seteaza Postgres real pentru productie; nimic
din codul de mai jos nu stie sau nu-i pasa care e dialectul.

``get_session`` e o functie modul-nivel stabila (nu o inchidere) ca sa poata fi
folosita drept cheie in ``app.dependency_overrides`` — patternul standard
FastAPI de testare: testele inlocuiesc ``get_session`` cu una legata de un
SQLite in-memory, fara sa atinga fisierul de productie.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importul e necesar (nu doar convenabil): clasele table=True se inregistreaza
# pe SQLModel.metadata doar cand modulul lor e importat. Fara linia asta,
# init_db() ar rula create_all() pe o metadata GOALA cand nimic altceva n-a
# importat inca models.py (exact bug-ul reparat aici dupa un test real cu
# uvicorn — create_all() nu arunca eroare, doar nu creeaza nimic).
import ppc_agent_server.models  # noqa: F401
from ppc_agent_server.settings import ServerSettings, get_server_settings

_engine: Engine | None = None


def create_db_engine(settings: ServerSettings | None = None) -> Engine:
    """Construieste un engine SQLAlchemy/SQLModel pentru ``settings.database_url``.

    ``check_same_thread=False`` e necesar doar pentru SQLite (FastAPI foloseste
    conexiunea din alt fir decat cel care a creat-o); e ignorat de alte dialecte.
    """
    resolved = settings or get_server_settings()
    is_sqlite = resolved.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    return create_engine(resolved.database_url, connect_args=connect_args)


def get_engine() -> Engine:
    """Engine-ul activ al procesului (creat lenes, o singura data)."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def set_engine(engine: Engine) -> None:
    """Inlocuieste engine-ul activ — folosit de teste (SQLite in-memory)."""
    global _engine
    _engine = engine


def init_db(engine: Engine | None = None) -> None:
    """Creeaza tabelele lipsa (echivalentul unei migratii Alembic ``upgrade head``
    pentru un SQLite de dezvoltare/test — in productie se foloseste Alembic)."""
    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    """Dependinta FastAPI: o sesiune per cerere, legata de engine-ul activ."""
    with Session(get_engine()) as session:
        yield session
