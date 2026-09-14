"""Teste pentru primitivele criptografice din security.py, izolat de DB/HTTP."""

from __future__ import annotations

from collections.abc import Iterator

import jwt
import pytest
from cryptography.fernet import Fernet, InvalidToken

from ppc_agent_server.security import (
    create_client_token,
    decode_client_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)
from ppc_agent_server.settings import get_server_settings


@pytest.fixture
def crypto_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """JWT_SECRET_KEY + SECRETS_KEY valide, izolate per test (vezi agency_settings
    din conftest.py pentru varianta cu Tenant/DB - aici testam doar security.py)."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-at-least-32-bytes-long")
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    get_server_settings.cache_clear()
    yield
    get_server_settings.cache_clear()


def test_password_hash_is_not_the_raw_password() -> None:
    hashed = hash_password("parola-mea-secreta")
    assert hashed != "parola-mea-secreta"
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_correct_password() -> None:
    hashed = hash_password("parola-mea-secreta")
    assert verify_password("parola-mea-secreta", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("parola-mea-secreta")
    assert verify_password("alta-parola", hashed) is False


def test_verify_password_rejects_corrupted_hash() -> None:
    assert verify_password("orice", "nu-e-un-hash-argon2-valid") is False


def test_create_client_token_without_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    get_server_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            create_client_token(1)
    finally:
        get_server_settings.cache_clear()


def test_client_token_roundtrip(crypto_settings: None) -> None:
    token = create_client_token(42)
    assert decode_client_token(token) == 42


def test_decode_rejects_tampered_token(crypto_settings: None) -> None:
    token = create_client_token(42)
    with pytest.raises(jwt.PyJWTError):
        decode_client_token(token + "tampered")


def test_decode_rejects_token_signed_with_different_secret(crypto_settings: None) -> None:
    token = create_client_token(42)
    other_token = jwt.encode(
        {"sub": "42"}, "alta-cheie-cu-totul-diferita-32-octeti", algorithm="HS256"
    )
    assert token != other_token
    with pytest.raises(jwt.PyJWTError):
        decode_client_token(other_token)


def test_encrypt_secret_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRETS_KEY", "")
    get_server_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            encrypt_secret("orice")
    finally:
        get_server_settings.cache_clear()


def test_encrypt_decrypt_secret_roundtrip(crypto_settings: None) -> None:
    encrypted = encrypt_secret("1//refresh-token-real")
    assert encrypted != "1//refresh-token-real"
    assert decrypt_secret(encrypted) == "1//refresh-token-real"


def test_decrypt_secret_rejects_value_encrypted_with_different_key(
    crypto_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    encrypted = encrypt_secret("secret")
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    get_server_settings.cache_clear()
    with pytest.raises(InvalidToken):
        decrypt_secret(encrypted)
