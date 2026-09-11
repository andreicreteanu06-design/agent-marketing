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
from ppc_agent_server.auth import create_tenant
from ppc_agent_server.db import init_db, set_engine
from ppc_agent_server.jobs.queue import InlineJobQueue, set_job_queue
from ppc_agent_server.models import Tenant


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


@pytest.fixture(autouse=True)
def _isolated_job_queue() -> None:
    """O coada noua per test — rezultatele unui test nu se scurg in urmatorul."""
    set_job_queue(InlineJobQueue())


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """Client FastAPI legat de engine-ul de test (vezi ``set_engine`` in fixture-ul de mai sus)."""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def tenant_and_key(session: Session) -> tuple[Tenant, str]:
    """O agentie noua + cheia ei API in clar (aratata o singura data, ca la creare reala)."""
    return create_tenant(session, "Agentie Test")


@pytest.fixture
def auth_headers(tenant_and_key: tuple[Tenant, str]) -> dict[str, str]:
    """Antetul ``Authorization`` gata de folosit in ``client.post(..., headers=...)``."""
    _, raw_key = tenant_and_key
    return {"Authorization": f"Bearer {raw_key}"}
