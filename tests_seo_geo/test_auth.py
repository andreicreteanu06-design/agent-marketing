"""Teste pentru get_current_client_id (decodarea token-ului JWT partajat)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from seo_geo_agent.auth import get_current_client_id
from seo_geo_agent.settings import SeoGeoSettings
from tests_seo_geo.conftest import TEST_CLIENT_USER_ID, TEST_JWT_SECRET, make_token


def test_missing_header_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_client_id(None)
    assert exc_info.value.status_code == 401


def test_malformed_header_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_client_id("NotBearer abc")
    assert exc_info.value.status_code == 401


def test_missing_secret_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suprascrie getter-ul cu setari explicite (nu doar sterge variabila de mediu):
    SeoGeoSettings mai citeste si fisierul .env real de pe disc, care poate avea
    deja JWT_SECRET_KEY completat pentru dezvoltarea ppc_agent_server - un kwarg
    explicit la constructie castiga mereu in fata oricarei surse de mediu/fisier."""
    monkeypatch.setattr(
        "seo_geo_agent.auth.get_seo_geo_settings",
        lambda: SeoGeoSettings(jwt_secret_key=""),
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_client_id(f"Bearer {make_token(secret='oricare')}")
    assert exc_info.value.status_code == 503


def test_valid_token_returns_client_id(jwt_settings: None) -> None:
    client_id = get_current_client_id(f"Bearer {make_token()}")
    assert client_id == TEST_CLIENT_USER_ID


def test_wrong_secret_raises_401(jwt_settings: None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_client_id(f"Bearer {make_token(secret='alt-secret')}")
    assert exc_info.value.status_code == 401


def test_expired_token_raises_401(jwt_settings: None) -> None:
    expired = jwt.encode(
        {
            "sub": str(TEST_CLIENT_USER_ID),
            "iat": datetime.now(tz=UTC) - timedelta(days=10),
            "exp": datetime.now(tz=UTC) - timedelta(days=3),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_client_id(f"Bearer {expired}")
    assert exc_info.value.status_code == 401
