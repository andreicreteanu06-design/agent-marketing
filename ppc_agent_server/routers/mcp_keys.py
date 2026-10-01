"""Cheile MCP ale clientului: ce ii dai unui agent AI extern ca sa-ti foloseasca datele.

- ``POST   /api/v1/me/mcp-keys``      - cheie noua; cheia in clar se arata O SINGURA DATA;
- ``GET    /api/v1/me/mcp-keys``      - cheile tale (fara cheie), ca sa stii ce ai dat cui;
- ``DELETE /api/v1/me/mcp-keys/{id}`` - revocarea: agentul pierde accesul la cererea urmatoare.

O cheie MCP merge doar pe serverul MCP (``routers/mcp_router.py``): unelte de citire si
propuneri care asteapta aprobarea ta. Nu poate aproba nimic, deci un agent care o are
nu poate cheltui bani. Revocarea pastreaza randul (cine, cand), nu-l sterge.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ppc_agent_server.auth import hash_api_key
from ppc_agent_server.db import get_session
from ppc_agent_server.models import ClientUser, McpAccessKey
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.routers.mcp_router import MCP_KEY_PREFIX, MCP_MOUNT_PATH, STREAM_PATH
from ppc_agent_server.schemas import McpKeyCreate, McpKeyCreated, McpKeyRead
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/me/mcp-keys", tags=["mcp-keys"])


@router.post("", response_model=McpKeyCreated, status_code=201)
def create_mcp_key(
    body: McpKeyCreate,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> McpKeyCreated:
    """Cheie noua pentru un agent extern. Cheia in clar nu se mai poate citi dupa asta."""
    raw_key = f"{MCP_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key = McpAccessKey(
        client_account_id=user.client_account_id,
        name=body.name.strip(),
        key_hash=hash_api_key(raw_key),
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    public_url = get_server_settings().public_api_url.rstrip("/")
    return McpKeyCreated(
        **McpKeyRead.model_validate(key).model_dump(),
        key=raw_key,
        mcp_url=f"{public_url}{MCP_MOUNT_PATH}{STREAM_PATH}",
    )


@router.get("", response_model=list[McpKeyRead])
def list_mcp_keys(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[McpAccessKey]:
    """Cheile clientului, cele mai noi primele - inclusiv cele revocate."""
    return list(
        session.exec(
            select(McpAccessKey)
            .where(McpAccessKey.client_account_id == user.client_account_id)
            .order_by(McpAccessKey.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


@router.delete("/{key_id}", response_model=McpKeyRead)
def revoke_mcp_key(
    key_id: int,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> McpAccessKey:
    """Revoca cheia (idempotent). 404 si pentru cheia altui client."""
    key = session.get(McpAccessKey, key_id)
    if key is None or key.client_account_id != user.client_account_id:
        raise HTTPException(status_code=404, detail="cheia nu exista")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(tz=UTC)
        session.add(key)
        session.commit()
        session.refresh(key)
    return key
