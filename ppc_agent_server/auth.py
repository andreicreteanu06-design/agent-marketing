"""Autentificare per-agentie prin cheie API (``Authorization: Bearer <cheie>``).

Fara flux de login — o agentie primeste o cheie generata o singura data (la
crearea contului, in afara acestui modul) si o trimite in fiecare cerere.
Doar hash-ul (SHA-256) se stocheaza in :class:`~ppc_agent_server.models.Tenant`;
cheia in clar nu poate fi recuperata daca se pierde, doar regenerata.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from ppc_agent_server.db import get_session
from ppc_agent_server.models import Tenant

_KEY_PREFIX = "pk_"


def hash_api_key(raw_key: str) -> str:
    """Hash-ul stocat pentru o cheie API in clar (SHA-256, hex)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Genereaza o cheie API noua.

    Returns:
        ``(cheia_in_clar, hash)`` — cheia in clar se arata utilizatorului o
        singura data (la creare); doar hash-ul se pastreaza in baza de date.
    """
    raw_key = f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_key, hash_api_key(raw_key)


def create_tenant(session: Session, name: str) -> tuple[Tenant, str]:
    """Creeaza o agentie noua si ii genereaza cheia API.

    Operatie administrativa (onboarding), nu un endpoint public — nu exista
    auto-inregistrare in API. Foloseste dintr-un script/CLI de administrare.

    Returns:
        ``(tenant, cheia_in_clar)`` — cheia se arata o singura data.
    """
    raw_key, key_hash = generate_api_key()
    tenant = Tenant(name=name, api_key_hash=key_hash)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant, raw_key


def get_current_tenant(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Tenant:
    """Dependinta FastAPI: rezolva agentia din antetul ``Authorization``.

    Raises:
        HTTPException: 401 daca antetul lipseste/e malformat sau cheia nu
            corespunde niciunei agentii; 403 daca abonamentul e suspendat.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="lipseste antetul 'Authorization: Bearer <cheie>'",
        )
    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="cheie API goala")

    tenant = session.exec(
        select(Tenant).where(Tenant.api_key_hash == hash_api_key(raw_key))
    ).first()
    if tenant is None:
        raise HTTPException(status_code=401, detail="cheie API invalida")
    if tenant.subscription_status == "suspended":
        raise HTTPException(status_code=403, detail="abonamentul agentiei este suspendat")
    return tenant
