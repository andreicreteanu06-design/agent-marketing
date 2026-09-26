"""Fixture-uri partajate: SQLite in-memory, izolat per test, fara Postgres real.

``StaticPool`` e obligatoriu pentru SQLite in-memory in teste: fara el, fiecare
conexiune noua ar vedea o baza de date in-memory goala, separata.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from ppc_agent_server.app import create_app
from ppc_agent_server.auth import create_tenant
from ppc_agent_server.db import init_db, set_engine
from ppc_agent_server.jobs import tasks
from ppc_agent_server.jobs.queue import InlineJobQueue, set_job_queue
from ppc_agent_server.models import Tenant
from ppc_agent_server.rate_limit import reset_rate_limits
from ppc_agent_server.services import researcher
from ppc_agent_server.settings import get_server_settings


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


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> None:
    """Limitele de frecventa sunt in memoria procesului - fiecare test incepe de la zero."""
    reset_rate_limits()


@pytest.fixture(autouse=True)
def _no_pagespeed_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mentenanta de noapte masoara viteza prin Google PageSpeed - niciodata din teste.

    Testele care verifica masuratoarea isi dau propriul ``measure``.
    """
    monkeypatch.setattr(tasks, "measure_mobile_speed", lambda url: None)


@pytest.fixture(autouse=True)
def _no_web_search(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Researcher-ul cauta pe web prin DuckDuckGo - niciodata din teste.

    Cautarea "pica" (starea ``failed``, gratios); testele care o verifica isi dau
    propriul ``search``. Cache-ul pe zi se goleste, ca rezultatele sa nu treaca
    dintr-un test in altul.
    """

    def _offline(query: str) -> list[dict[str, str]]:
        raise ConnectionError("fara retea in teste")

    monkeypatch.setattr(researcher, "ddgs_text", _offline)
    researcher._cached_search.cache_clear()
    yield
    researcher._cached_search.cache_clear()


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


@pytest.fixture
def agency_settings(
    tenant_and_key: tuple[Tenant, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Tenant]:
    """Configureaza JWT_SECRET_KEY/SECRETS_KEY/AGENCY_TENANT_ID pentru un test -
    necesar pentru orice test care loveste /signup, /login, /me, /me/credentials
    sau _app_config_for cu secrete criptate. get_server_settings() e cache-uit
    (lru_cache) - trebuie golit inainte SI dupa, altfel setarile "scurg" in
    alte teste care ruleaza in acelasi proces."""
    tenant, _ = tenant_and_key
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AGENCY_TENANT_ID", str(tenant.id))
    get_server_settings.cache_clear()
    yield tenant
    get_server_settings.cache_clear()
