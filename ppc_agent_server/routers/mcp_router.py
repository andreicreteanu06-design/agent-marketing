"""Montarea serverului MCP peste SSE, in aceeasi aplicatie FastAPI.

Doua rute, generate de SDK-ul MCP:

- ``GET  /api/v1/mcp/sse``      - conexiunea lunga pe care clientul o tine deschisa;
- ``POST /api/v1/mcp/messages`` - mesajele pe care le trimite inapoi.

Autentificarea e OBLIGATORIE pe amandoua, cu acelasi token de client ca restul
zonei ``/cont``. Fara ea, oricine ar putea deschide o conexiune si citi datele
oricarui client - uneltele nu primesc id-ul contului ca parametru tocmai ca sa
nu poata fi ales din afara (vezi ``mcp/server.py``).

Un detaliu de transport care dicteaza unde se face autentificarea: la SSE,
``POST /messages`` doar depune mesajul intr-o coada, iar unealta se executa in
task-ul conexiunii ``GET /sse``. Deci contextul de client trebuie legat de
conexiunea GET - acolo il seteaza middleware-ul. POST-ul e verificat separat,
ca un id de sesiune ghicit sa nu permita injectarea de mesaje.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from sqlmodel import Session
from starlette.types import Receive, Scope, Send

from ppc_agent_server.db import get_engine
from ppc_agent_server.mcp.server import (
    build_server,
    reset_client_account_id,
    set_client_account_id,
)
from ppc_agent_server.models import ClientUser
from ppc_agent_server.security import decode_client_token

logger = logging.getLogger("ppc_agent_server.routers.mcp")

MCP_MOUNT_PATH = "/api/v1/mcp"
SSE_PATH = "/sse"
MESSAGE_PATH = "/messages"


def _bearer_token(scope: Scope) -> str:
    """Token-ul din antetul ``Authorization``, sau "" daca lipseste/e malformat."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for name, value in headers:
        if name.lower() == b"authorization":
            raw = value.decode("latin-1")
            if raw.startswith("Bearer "):
                return raw.removeprefix("Bearer ").strip()
    return ""


def _resolve_client_account_id(token: str) -> int | None:
    """Contul clientului din token, sau ``None`` daca token-ul nu e valabil."""
    if not token:
        return None
    try:
        client_user_id = decode_client_token(token)
    except (jwt.PyJWTError, ValueError):
        return None
    with Session(get_engine()) as session:
        user = session.get(ClientUser, client_user_id)
        return user.client_account_id if user is not None else None


async def _reject_unauthorized(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": (
                b'{"detail":"lipseste sau e invalid antetul '
                b'\'Authorization: Bearer <token de client>\'"}'
            ),
        }
    )


def authenticated_mcp_app(app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> Any:
    """Invelis ASGI care cere token de client si leaga conexiunea de contul lui.

    ``contextvars`` setate aici raman vizibile in tot ce ruleaza mai jos pe
    acelasi task - inclusiv in sesiunea MCP pornita de conexiunea SSE, deci si
    in uneltele apelate de ea.
    """

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        account_id = _resolve_client_account_id(_bearer_token(scope))
        if account_id is None:
            await _reject_unauthorized(send)
            return

        token = set_client_account_id(account_id)
        try:
            await app(scope, receive, send)
        finally:
            reset_client_account_id(token)

    return wrapped


def build_mcp_asgi_app() -> Any:
    """Aplicatia ASGI gata de montat la :data:`MCP_MOUNT_PATH`."""
    sse_app = build_server().sse_app(sse_path=SSE_PATH, message_path=MESSAGE_PATH)
    return authenticated_mcp_app(sse_app)
