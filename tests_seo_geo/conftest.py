"""Fixture-uri partajate pentru testele seo_geo_agent.

Nu importa nimic din ``ppc_agent_server`` (agent separat, vezi
``seo_geo_agent/__init__.py``) - token-ul de test e construit local cu ``jwt``,
acelasi algoritm/secret pe care le-ar produce ``create_client_token`` de acolo.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from seo_geo_agent.app import create_app
from seo_geo_agent.settings import get_seo_geo_settings

_JWT_ALGORITHM = "HS256"
TEST_JWT_SECRET = "test-jwt-secret-not-for-production"
TEST_CLIENT_USER_ID = 42


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
    with TestClient(create_app()) as test_client:
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
