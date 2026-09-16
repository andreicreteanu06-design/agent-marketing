"""Autentificare: valideaza token-ul JWT emis de ``ppc_agent_server`` (POST /api/v1/login).

Acelasi algoritm/secret ca ``ppc_agent_server/security.py`` (``create_client_token``) -
implementat independent aici (agent separat, vezi ``__init__.py``), nu importat,
ca acest serviciu sa ramana instalabil/rulabil fara ``ppc_agent_server`` ca
dependinta. Nu atinge nicio baza de date: doar semnatura si expirarea sunt
verificate - id-ul clientului (``sub``) e suficient pentru a proteja acest
endpoint, analiza nu are nevoie de restul profilului clientului.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Header, HTTPException

from seo_geo_agent.settings import get_seo_geo_settings

_JWT_ALGORITHM = "HS256"


def get_current_client_id(authorization: Annotated[str | None, Header()] = None) -> int:
    """Dependinta FastAPI: id-ul ``ClientUser`` autentificat, din antetul ``Authorization``.

    Raises:
        HTTPException: 401 daca antetul lipseste/e malformat sau token-ul e
            invalid/expirat; 503 daca serviciul nu are ``JWT_SECRET_KEY`` configurat.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="lipseste antetul 'Authorization: Bearer <token>'"
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="token gol")

    settings = get_seo_geo_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=503, detail="JWT_SECRET_KEY nu e configurat pe acest serviciu"
        )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="token invalid sau expirat") from exc
