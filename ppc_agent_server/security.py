"""Criptografie pentru autentificarea clientilor si stocarea cheilor API.

Trei responsabilitati distincte, separate deliberat de ``auth.py`` (care
ramane neschimbat - autentificarea de AGENTIE, prin cheie API, nu prin
parola):

- hash de parola (Argon2id - recomandarea OWASP curenta, inlocuieste
  ``passlib``, care nu mai e activ intretinut)
- token JWT (sesiunea unui ``ClientUser`` dupa login)
- criptare simetrica (Fernet) a secretelor stocate per client (refresh
  tokens/access tokens de pe conturile de reclame ale clientului) - vezi
  ``ClientAccount.*_enc`` in ``models.py``
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from ppc_agent_server.settings import get_server_settings

_password_hasher = PasswordHasher()
_JWT_ALGORITHM = "HS256"
_JWT_TTL = timedelta(days=7)
#: Cat are clientul la dispozitie pe ecranul de consimtamant Google.
_OAUTH_STATE_TTL = timedelta(minutes=10)
_OAUTH_STATE_AUDIENCE = "oauth-state"

__all__ = [
    "InvalidToken",
    "create_client_token",
    "create_oauth_state",
    "decode_client_token",
    "decode_oauth_state",
    "decrypt_secret",
    "encrypt_secret",
    "hash_password",
    "verify_password",
]


def hash_password(raw_password: str) -> str:
    """Hash Argon2id - ireversibil, doar verificabil prin :func:`verify_password`."""
    return _password_hasher.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    """Verifica parola in clar impotriva hash-ului stocat.

    ``False`` atat pentru parola gresita cat si pentru un hash corupt/vechi
    (``InvalidHashError``) - apelantul nu are nevoie sa distinga cauza.
    """
    try:
        return _password_hasher.verify(password_hash, raw_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_client_token(client_user_id: int) -> str:
    """Token JWT semnat, valabil 7 zile - identitatea unui ``ClientUser`` autentificat.

    Raises:
        RuntimeError: ``JWT_SECRET_KEY`` nu e configurat in mediu.
    """
    settings = get_server_settings()
    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY nu e configurat - genereaza unul si pune-l in .env "
            '(ex: python -c "import secrets; print(secrets.token_urlsafe(32))")'
        )
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {"sub": str(client_user_id), "iat": now, "exp": now + _JWT_TTL}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_client_token(token: str) -> int:
    """Decodeaza si valideaza un token JWT, intoarce ``client_user_id``.

    Raises:
        RuntimeError: ``JWT_SECRET_KEY`` nu e configurat in mediu.
        jwt.PyJWTError: Token invalid, expirat, sau semnat cu alta cheie.
    """
    settings = get_server_settings()
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY nu e configurat - vezi create_client_token")
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    return int(payload["sub"])


def _oauth_state_key() -> str:
    """Cheia de semnare a starii OAuth, DERIVATA din ``JWT_SECRET_KEY``.

    Nu cheia sesiunilor insasi: starea circula in URL-uri (ecranul Google,
    istoricul browserului), iar ``decode_client_token`` - ca si verificarea din
    ``seo_geo_agent`` - accepta orice token semnat cu cheia sesiunilor. Cu o
    cheie derivata, o stare nu poate trece niciodata drept sesiune.
    """
    settings = get_server_settings()
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY nu e configurat - vezi create_client_token")
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"), b"oauth-state", hashlib.sha256
    ).hexdigest()


def create_oauth_state(client_account_id: int, integration: str) -> str:
    """Starea semnata trimisa la Google si primita inapoi pe callback.

    Leaga raspunsul Google de contul care a CERUT conectarea si de integrarea
    ceruta: callback-ul nu are sesiunea clientului (e o redirectionare din
    browser, fara antetul ``Authorization``), deci contul nu poate veni din
    alta parte. Valabila 10 minute.
    """
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "acct": client_account_id,
        "int": integration,
        "aud": _OAUTH_STATE_AUDIENCE,
        "nonce": secrets.token_urlsafe(8),
        "iat": now,
        "exp": now + _OAUTH_STATE_TTL,
    }
    return jwt.encode(payload, _oauth_state_key(), algorithm=_JWT_ALGORITHM)


def decode_oauth_state(state: str, integration: str) -> int:
    """Contul din starea OAuth, doar daca starea e valida pentru ``integration``.

    Raises:
        RuntimeError: ``JWT_SECRET_KEY`` nu e configurat in mediu.
        jwt.PyJWTError: stare falsificata, expirata sau emisa pentru alta integrare.
    """
    payload = jwt.decode(
        state, _oauth_state_key(), algorithms=[_JWT_ALGORITHM], audience=_OAUTH_STATE_AUDIENCE
    )
    if payload.get("int") != integration:
        raise jwt.InvalidTokenError("starea a fost emisa pentru alta integrare")
    return int(payload["acct"])


def _fernet() -> Fernet:
    settings = get_server_settings()
    if not settings.secrets_key:
        raise RuntimeError(
            "SECRETS_KEY nu e configurat - genereaza unul si pune-l in .env "
            '(ex: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())")'
        )
    return Fernet(settings.secrets_key.encode("utf-8"))


def encrypt_secret(raw_value: str) -> str:
    """Cripteaza un secret (ex. refresh token) pentru stocare in DB."""
    return _fernet().encrypt(raw_value.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_value: str) -> str:
    """Decripteaza un secret stocat.

    Raises:
        cryptography.fernet.InvalidToken: ``SECRETS_KEY`` gresit sau valoare coruptă.
    """
    return _fernet().decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
