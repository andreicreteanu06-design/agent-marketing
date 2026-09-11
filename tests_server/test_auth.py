"""Teste pentru autentificarea per-agentie prin cheie API."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from ppc_agent_server.auth import (
    create_tenant,
    generate_api_key,
    get_current_tenant,
    hash_api_key,
)
from ppc_agent_server.models import SubscriptionStatus, Tenant


def test_generate_api_key_is_prefixed_and_hash_matches() -> None:
    raw_key, key_hash = generate_api_key()
    assert raw_key.startswith("pk_")
    assert key_hash == hash_api_key(raw_key)
    assert key_hash != raw_key  # hash-ul nu e cheia in clar


def test_generate_api_key_is_not_deterministic() -> None:
    first_raw, first_hash = generate_api_key()
    second_raw, second_hash = generate_api_key()
    assert first_raw != second_raw
    assert first_hash != second_hash


def test_create_tenant_persists_and_returns_raw_key_once(session: Session) -> None:
    tenant, raw_key = create_tenant(session, "Agentie Noua")
    assert tenant.id is not None
    assert tenant.api_key_hash == hash_api_key(raw_key)
    assert tenant.subscription_status == SubscriptionStatus.TRIAL

    fetched = session.get(Tenant, tenant.id)
    assert fetched is not None
    assert fetched.api_key_hash == hash_api_key(raw_key)


def test_get_current_tenant_resolves_valid_key(session: Session) -> None:
    tenant, raw_key = create_tenant(session, "Agentie Valida")
    resolved = get_current_tenant(session=session, authorization=f"Bearer {raw_key}")
    assert resolved.id == tenant.id


def test_get_current_tenant_missing_header_raises_401(session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        get_current_tenant(session=session, authorization=None)
    assert excinfo.value.status_code == 401


def test_get_current_tenant_malformed_header_raises_401(session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        get_current_tenant(session=session, authorization="NotBearer xyz")
    assert excinfo.value.status_code == 401


def test_get_current_tenant_unknown_key_raises_401(session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        get_current_tenant(session=session, authorization="Bearer pk_nu_exista")
    assert excinfo.value.status_code == 401


def test_get_current_tenant_suspended_raises_403(session: Session) -> None:
    tenant, raw_key = create_tenant(session, "Agentie Suspendata")
    tenant.subscription_status = SubscriptionStatus.SUSPENDED
    session.add(tenant)
    session.commit()

    with pytest.raises(HTTPException) as excinfo:
        get_current_tenant(session=session, authorization=f"Bearer {raw_key}")
    assert excinfo.value.status_code == 403
