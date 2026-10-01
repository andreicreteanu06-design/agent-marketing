"""Montarea serverului MCP in aplicatia FastAPI - poarta prin care agentii AI externi
(ChatGPT, Claude, Cursor, n8n, agenti scrisi cu OpenAI Agents SDK sau LangChain)
folosesc datele platformei.

Doua transporturi, acelasi server si aceleasi unelte (``mcp/server.py``):

- **Streamable HTTP** - ``POST /api/v1/mcp/stream``: transportul standard actual al
  MCP, pe care il stiu agentii de la distanta. Fara stare (``stateless``): fiecare
  cerere e independenta, deci merge si cu mai multi workeri uvicorn;
- **SSE** (vechi, pastrat pentru clientii existenti) - ``GET /api/v1/mcp/sse`` plus
  ``POST /api/v1/mcp/messages``.

Autentificarea e OBLIGATORIE, cu ``Authorization: Bearer <cheie>``:

- o **cheie MCP** (``mcp_...``, ``routers/mcp_keys.py``) - ce primeste un agent extern:
  merge doar aici, nu expira, se revoca oricand, si e legata de UN client;
- token-ul de login al clientului (pentru interfata proprie). Nu-l dai unui agent:
  el deschide tot contul, inclusiv aprobarea cheltuielilor.

Uneltele nu primesc id-ul contului ca parametru, tocmai ca sa nu poata fi ales din
afara: contul vine din cheie, legat de cerere printr-un ``contextvar``.

Un detaliu de transport care dicteaza unde se face autentificarea: la SSE,
``POST /messages`` doar depune mesajul intr-o coada, iar unealta se executa in
task-ul conexiunii ``GET /sse``. Deci contextul de client trebuie legat de
conexiunea GET - acolo il seteaza middleware-ul. POST-ul e verificat separat,
ca un id de sesiune ghicit sa nu permita injectarea de mesaje. La Streamable HTTP,
fiecare POST poarta cheia si isi seteaza singur contextul.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlmodel import Session, select
from starlette.applications import Starlette
from starlette.types import Receive, Scope, Send

from ppc_agent_server.auth import hash_api_key
from ppc_agent_server.db import get_engine
from ppc_agent_server.mcp.server import (
    build_server,
    reset_client_account_id,
    set_client_account_id,
)
from ppc_agent_server.models import ClientUser, McpAccessKey
from ppc_agent_server.security import decode_client_token

logger = logging.getLogger("ppc_agent_server.routers.mcp")

MCP_MOUNT_PATH = "/api/v1/mcp"
STREAM_PATH = "/stream"
SSE_PATH = "/sse"
MESSAGE_PATH = "/messages"
#: Prefixul cheilor MCP (``routers/mcp_keys.py``) - le desparte de token-urile de login.
MCP_KEY_PREFIX = "mcp_"

#: Protectia anti-DNS-rebinding a SDK-ului accepta implicit doar ``localhost`` - un
#: agent care vine prin domeniul public ar fi refuzat. Aici nu e nevoie de ea: atacul
#: "imprumuta" credentiale pe care browserul le trimite singur (cookie-uri), iar noi
#: cerem o cheie in ``Authorization``, pe care o pagina straina nu o are.
_NO_HOST_PINNING = TransportSecuritySettings(enable_dns_rebinding_protection=False)


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
    """Contul clientului din cheia MCP sau din token-ul de login; ``None`` = invalid."""
    if not token:
        return None
    with Session(get_engine()) as session:
        if token.startswith(MCP_KEY_PREFIX):
            key = session.exec(
                select(McpAccessKey).where(McpAccessKey.key_hash == hash_api_key(token))
            ).first()
            if key is None or key.revoked_at is not None:
                return None
            return key.client_account_id
        try:
            client_user_id = decode_client_token(token)
        except (jwt.PyJWTError, ValueError):
            return None
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
                b'\'Authorization: Bearer <cheie MCP>\'"}'
            ),
        }
    )


def authenticated_mcp_app(app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> Any:
    """Invelis ASGI care cere o cheie valida si leaga cererea de contul ei.

    ``contextvars`` setate aici raman vizibile in tot ce ruleaza mai jos pe
    acelasi task - si in task-urile pornite de el (sesiunea MCP a conexiunii SSE,
    serverul fara stare al unei cereri Streamable HTTP), deci si in unelte.
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


def build_mcp_asgi_app() -> tuple[Any, StreamableHTTPSessionManager]:
    """Aplicatia ASGI gata de montat la :data:`MCP_MOUNT_PATH` si managerul de sesiuni.

    Managerul trebuie pornit in lifespan-ul aplicatiei FastAPI (``app.py``): o
    aplicatie montata nu-si ruleaza singura lifespan-ul.
    """
    server = build_server()
    stream = server.streamable_http_app(
        streamable_http_path=STREAM_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=_NO_HOST_PINNING,
    )
    sse = server.sse_app(
        sse_path=SSE_PATH, message_path=MESSAGE_PATH, transport_security=_NO_HOST_PINNING
    )
    app = Starlette(routes=[*stream.routes, *sse.routes])
    return authenticated_mcp_app(app), server.session_manager
