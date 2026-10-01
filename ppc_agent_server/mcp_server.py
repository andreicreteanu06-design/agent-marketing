"""Serverul MCP al agentiei pe stdio - pentru Claude Desktop si alte aplicatii LLM locale.

Acelasi server ca in aplicatia web (``mcp/server.py``: aceleasi unelte, aceleasi date
reale), doar alt transport. Pe SSE contul clientului vine din token; aici nu exista
token, deci il fixeaza cine porneste procesul, prin ``MCP_CLIENT_ACCOUNT_ID`` - o
conexiune stdio vede un singur client, ales de operator, nu de model.

    MCP_CLIENT_ACCOUNT_ID=3 python -m ppc_agent_server.mcp_server

Pe stdio, stdout e canalul protocolului: nimic altceva nu are voie sa scrie acolo
(erorile de pornire pleaca pe stderr, prin ``sys.exit``).
"""

from __future__ import annotations

import os
import sys

from sqlmodel import Session

from ppc_agent_server.db import get_engine
from ppc_agent_server.mcp.server import build_server, set_client_account_id
from ppc_agent_server.models import ClientAccount


def main() -> None:
    raw = os.environ.get("MCP_CLIENT_ACCOUNT_ID", "").strip()
    if not raw.isdigit():
        sys.exit("MCP_CLIENT_ACCOUNT_ID lipsește: id-ul contului de client pe care îl servește.")
    account_id = int(raw)
    with Session(get_engine()) as session:
        if session.get(ClientAccount, account_id) is None:
            sys.exit(f"Contul de client {account_id} nu există în baza de date.")
    set_client_account_id(account_id)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
