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

from ppc_agent.errors import ProviderError
from ppc_agent_server.app import create_app
from ppc_agent_server.auth import create_tenant
from ppc_agent_server.db import init_db, set_engine
from ppc_agent_server.jobs import synthetic, tasks
from ppc_agent_server.jobs.queue import InlineJobQueue, set_job_queue
from ppc_agent_server.models import Tenant
from ppc_agent_server.rate_limit import reset_rate_limits
from ppc_agent_server.routers import campaigns as campaigns_router
from ppc_agent_server.services import geocoding, market_trends
from ppc_agent_server.services.llm_client import reset_llm_state
from ppc_agent_server.settings import get_server_settings
from ppc_agent_server.skills import web_search
from tests_server.llm_fakes import FakeJev, FakeOllama


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
def _no_site_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditul SEO/GEO de noapte crawleaza site-ul clientului - niciodata din teste.

    Testele auditului isi dau propriul ``audit``.
    """
    monkeypatch.setattr(tasks, "run_site_audit", lambda url, brand: None)


@pytest.fixture(autouse=True)
def _no_google_trends(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Google Trends (``pytrends``) - niciodata real din teste.

    Cererea "pica" (ramane necunoscuta, cu o nota); testele care o verifica isi dau
    propria sursa. Cache-ul pe zi si pauza dupa esec se golesc intre teste.
    """

    def _offline(
        keyword: str, geo: str, timeframe: str = market_trends.TIMEFRAME
    ) -> list[market_trends.TrendPoint]:
        raise market_trends.TrendsUnavailableError("fara retea in teste")

    monkeypatch.setattr(market_trends, "pytrends_interest", _offline)
    market_trends.google_trends.clear()
    yield
    market_trends.google_trends.clear()


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testul sintetic de noapte porneste un Chromium - niciodata din alte teste.

    Testele monitorizarii isi dau propriul ``record`` (sau pornesc browserul explicit).
    """

    async def _unavailable(contract: object) -> None:
        raise ImportError("fara browser in teste")

    monkeypatch.setattr(synthetic, "record_journey", _unavailable)


@pytest.fixture(autouse=True)
def _no_web_search(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Abilitatea ``web_search`` cauta prin DuckDuckGo - niciodata din teste.

    Cautarea "pica" (starea ``failed``, gratios); testele care o verifica isi dau
    propriul registru de abilitati. Cache-ul pe zi se goleste, ca rezultatele sa nu
    treaca dintr-un test in altul.
    """

    def _offline(query: str) -> list[dict[str, str]]:
        raise ConnectionError("fara retea in teste")

    monkeypatch.setattr(web_search, "ddgs_text", _offline)
    web_search._cached_search.cache_clear()
    yield
    web_search._cached_search.cache_clear()


@pytest.fixture(autouse=True)
def _no_llm_services(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Jev si Ollama - niciodata reali din teste, oricare ar fi ``.env``-ul masinii.

    Fara ``JEV_API_KEY`` si fara ``OLLAMA_HOST``, ruterul hibrid nu are unde trimite
    nimic: consiliul si Regina raspund determinist, iar CI-ul trece si fara
    serviciile pornite. Testele care verifica drumul complet cer ``fake_jev`` /
    ``fake_ollama``. Serverele Ollama gasite "oprite" se uita intre teste.
    """
    monkeypatch.setenv("JEV_API_KEY", "")
    monkeypatch.setenv("OLLAMA_HOST", "")
    get_server_settings.cache_clear()
    reset_llm_state()
    yield
    get_server_settings.cache_clear()
    reset_llm_state()


@pytest.fixture(autouse=True)
def _no_real_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adresa afacerii nu pleaca la OpenStreetMap din teste: harta "nu raspunde".

    Testele interviului isi dau propria harta (``get_geocoder`` inlocuit).
    """

    def offline(address: str, country: str, **_: object) -> None:
        raise ProviderError("harta nu ruleaza in teste")

    monkeypatch.setattr(geocoding, "nominatim_geocode", offline)


@pytest.fixture(autouse=True)
def _no_real_cco(monkeypatch: pytest.MonkeyPatch) -> None:
    """CCO-ul la lansare nu descarca imagini si nu cheama Ollama din teste.

    Lansarea merge mai departe ca atunci cand CCO-ul nu poate rula; testele care vor un
    verdict anume inlocuiesc ``get_creative_review`` (vezi ``test_campaign_launch``).
    """

    async def offline(media_url: str, **_: object) -> bytes:
        raise ProviderError("CCO-ul nu ruleaza in teste")

    monkeypatch.setattr(campaigns_router, "download_media", offline)


@pytest.fixture
def fake_jev() -> Iterator[FakeJev]:
    """Jev simulat, raspuns instant; testul pica daca o cerere n-are forma documentata."""
    fake = FakeJev()
    yield fake
    assert fake.problems == [], fake.problems


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeOllama]:
    """Ollama simulat, raspuns instant; testul pica daca o cerere n-are forma documentata.

    Cu el, sinteza consiliului e pornita (``USE_LLM_SYNTHESIS``): testul vrea drumul LLM.
    """
    monkeypatch.setenv("USE_LLM_SYNTHESIS", "true")
    get_server_settings.cache_clear()
    fake = FakeOllama()
    yield fake
    assert fake.problems == [], fake.problems


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
