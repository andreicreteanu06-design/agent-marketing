"""Fixture-uri partajate: SQLite in-memory, izolat per test, fara Postgres real.

``StaticPool`` e obligatoriu pentru SQLite in-memory in teste: fara el, fiecare
conexiune noua ar vedea o baza de date in-memory goala, separata.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from ppc_agent_server.app import create_app
from ppc_agent_server.db import init_db, set_engine


@pytest.fixture
def engine() -> Iterator[Engine]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(test_engine)
    set_engine(test_engine)
    yield test_engine
    SQLModel.metadata.drop_all(test_engine)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """Client FastAPI legat de engine-ul de test (vezi ``set_engine`` in fixture-ul de mai sus)."""
    with TestClient(create_app()) as test_client:
        yield test_client
