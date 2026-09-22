"""Fixture-uri partajate pentru testele seo_geo_agent.

Nu importa nimic din ``ppc_agent_server`` (agent separat, vezi
``seo_geo_agent/__init__.py``) - token-ul de test e construit local cu ``jwt``,
acelasi algoritm/secret pe care le-ar produce ``create_client_token`` de acolo.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from seo_geo_agent import router as router_module
from seo_geo_agent.app import create_app
from seo_geo_agent.audit.page_analyzer import PageLink, StructuredData
from seo_geo_agent.audit.types import CrawledPage
from seo_geo_agent.settings import get_seo_geo_settings

_JWT_ALGORITHM = "HS256"
TEST_JWT_SECRET = "test-jwt-secret-not-for-production"
TEST_CLIENT_USER_ID = 42


async def _fake_auto_fetch(domain: str) -> str:
    """Inlocuieste implicit ``_fetch_real_data_report`` in teste - text canonic,
    fara niciun apel de retea (PageSpeed Insights/Microlink raman neatinse -
    vezi README.md "Toate testele ruleaza fara retea"). Testele care verifica
    explicit comportamentul de auto-fetch (gol, combinat cu raport manual etc.)
    isi suprascriu propriul dependency_overrides peste acesta."""
    return f"[test] date auto-preluate simulate pentru {domain}"


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configureaza JWT_SECRET_KEY pentru un test - vezi tests_server/conftest.py
    pentru precedentul acestui pattern (get_seo_geo_settings e cache-uit cu
    lru_cache, trebuie golit inainte SI dupa, altfel setarile "scurg" in alte
    teste care ruleaza in acelasi proces)."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_seo_geo_settings.cache_clear()
    yield
    get_seo_geo_settings.cache_clear()


@pytest.fixture
def client(jwt_settings: None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[router_module._get_auto_fetcher] = lambda: _fake_auto_fetch
    with TestClient(app) as test_client:
        yield test_client


def make_token(client_user_id: int = TEST_CLIENT_USER_ID, *, secret: str = TEST_JWT_SECRET) -> str:
    """Token JWT valid, in acelasi format ca ``ppc_agent_server.security.create_client_token``."""
    now = datetime.now(tz=UTC)
    payload = {"sub": str(client_user_id), "iat": now, "exp": now + timedelta(days=7)}
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


@pytest.fixture
def auth_headers(jwt_settings: None) -> dict[str, str]:
    """Antetul ``Authorization`` gata de folosit in ``client.post(..., headers=...)``."""
    return {"Authorization": f"Bearer {make_token()}"}


def make_page(url: str = "https://exemplu.ro/", **overrides: Any) -> CrawledPage:
    """O pagina crawlata "sanatoasa", peste care testul schimba doar ce verifica.

    Valorile implicite sunt alese ca sa NU declanseze nicio verificare: orice
    problema care apare intr-un test vine din ce a suprascris testul, nu din
    fixture. Vezi ``seo_geo_agent/audit/page_reporters.py`` pentru praguri.
    """
    defaults: dict[str, Any] = {
        "status_code": 200,
        "fetch_class": "ok",
        "title": "Un titlu perfect rezonabil pentru pagina",
        "meta_description": (
            "O meta description de lungime potrivita, intre saptezeci si o suta saizeci "
            "de caractere, exact cum cere verificarea."
        ),
        "h1_count": 1,
        "heading_order": [1, 2],
        "word_count": 500,
        "body_text": "text " * 500,
        "is_html": True,
        "html_bytes": 30_000,
        "is_indexable": True,
        "response_time_ms": 200,
        "crawl_depth": 0,
        "links": [
            PageLink(
                target_url="https://exemplu.ro/alta",
                anchor="alta",
                is_internal=True,
                is_nofollow=False,
            )
        ],
        "structured_data": StructuredData(present=True, types=["WebPage"]),
    }
    return CrawledPage(url=url, **{**defaults, **overrides})
