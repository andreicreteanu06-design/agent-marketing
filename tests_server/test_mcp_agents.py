"""Agentii AI externi conectati prin MCP: cheile, Streamable HTTP si stdio, cap-coada.

Ce promitem unui agent extern si ce promitem clientului care i-a dat cheia:

- agentul vorbeste MCP standard (``initialize``, ``tools/list``, ``tools/call``) pe
  ``POST /api/v1/mcp/stream``, prin domeniul public (nu doar ``localhost``);
- vede DOAR clientul cheii, iar cheia nu deschide restul API-ului (aprobarile);
- o cheie revocata se opreste la cererea urmatoare;
- acelasi server merge si pe stdio (Claude Desktop / Claude Code locale).
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlmodel import Session, SQLModel, create_engine

from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    Tenant,
)

STREAM = "/api/v1/mcp/stream"
#: Ce trimite orice client Streamable HTTP: accepta si JSON, si flux SSE.
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
ROOT = Path(__file__).resolve().parents[1]


def _signup(client: TestClient, email: str, name: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/signup", json={"name": name, "email": email, "password": "parola-sigura-123"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _new_key(client: TestClient, login: dict[str, str], name: str = "ChatGPT") -> dict[str, Any]:
    response = client.post("/api/v1/me/mcp-keys", headers=login, json={"name": name})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _rpc(
    client: TestClient, key: str, method: str, params: dict[str, Any] | None = None
) -> Any:
    response = client.post(
        STREAM,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


@pytest.fixture
def owner(client: TestClient, agency_settings: Tenant) -> dict[str, str]:
    return _signup(client, "agent@service-demo.ro", "Service Demo SRL")


def test_cheia_se_arata_o_singura_data_cu_adresa_serverului(
    client: TestClient, owner: dict[str, str]
) -> None:
    created = _new_key(client, owner, "n8n agentie")

    assert created["key"].startswith("mcp_")
    assert created["mcp_url"].endswith("/api/v1/mcp/stream")
    [listed] = client.get("/api/v1/me/mcp-keys", headers=owner).json()
    assert listed["name"] == "n8n agentie"
    assert "key" not in listed  # cheia in clar nu se mai poate citi


def test_un_agent_extern_vorbeste_mcp_standard_si_vede_doar_clientul_cheii(
    client: TestClient, owner: dict[str, str]
) -> None:
    key = _new_key(client, owner)["key"]
    # Alt client, cu cheltuiala lui: agentul primului client nu trebuie s-o vada.
    other = _signup(client, "altul@exemplu.ro", "Alt Client SRL")
    _new_key(client, other)

    init = _rpc(
        client,
        key,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "agent-extern", "version": "1.0"},
        },
    )
    assert init["serverInfo"]["name"] == "Arting_Hybrid_Engine"
    tools = {tool["name"] for tool in _rpc(client, key, "tools/list")["tools"]}
    assert tools == {
        "get_cannibalization_insights",
        "get_seo_opportunities",
        "get_budget_summary",
        "propose_budget_change",
        "report_creative_performance",
        "get_creative_lessons",
    }
    summary = _rpc(client, key, "tools/call", {"name": "get_budget_summary", "arguments": {}})
    assert summary["structuredContent"]["client"] == "Service Demo SRL"


def test_propunerea_unui_agent_asteapta_omul(
    client: TestClient, owner: dict[str, str], session: Session
) -> None:
    key = _new_key(client, owner)["key"]
    result = _rpc(
        client,
        key,
        "tools/call",
        {
            "name": "propose_budget_change",
            "arguments": {
                "keyword": "service auto",
                "proposed_daily_budget": 30,
                "rationale": "test agent extern",
            },
        },
    )
    assert result["structuredContent"]["applied"] is False
    change = session.get(ProposedChange, result["structuredContent"]["proposed_change_id"])
    assert change is not None and change.status is ChangeStatus.PENDING


def test_cheia_mcp_nu_deschide_restul_api_ului(
    client: TestClient, owner: dict[str, str], session: Session
) -> None:
    """Cu cheia MCP un agent nu poate aproba nimic: nici /me, nici aprobarile."""
    key = {"Authorization": f"Bearer {_new_key(client, owner)['key']}"}
    account_id = client.get("/api/v1/me", headers=owner).json()["account"]["id"]
    change = ProposedChange(
        client_account_id=account_id,
        op=ChangeOp.UPDATE,
        resource="meta_ad_set/1",
        resource_type="ad_set",
        projected_daily_spend=Decimal("10"),
        rationale="test",
        source_module="test",
    )
    session.add(change)
    session.commit()

    assert client.get("/api/v1/me", headers=key).status_code == 401
    assert client.post(f"/api/v1/proposals/{change.id}/approve", headers=key).status_code == 401


def test_o_cheie_revocata_se_opreste_la_cererea_urmatoare(
    client: TestClient, owner: dict[str, str]
) -> None:
    created = _new_key(client, owner)
    assert _rpc(client, created["key"], "tools/list")["tools"]

    revoked = client.delete(f"/api/v1/me/mcp-keys/{created['id']}", headers=owner)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None

    response = client.post(
        STREAM,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {created['key']}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401


def test_nu_poti_revoca_cheia_altui_client(client: TestClient, owner: dict[str, str]) -> None:
    other = _signup(client, "altul@exemplu.ro", "Alt Client SRL")
    theirs = _new_key(client, other)
    assert client.delete(f"/api/v1/me/mcp-keys/{theirs['id']}", headers=owner).status_code == 404


@pytest.mark.parametrize("authorization", [None, "Bearer mcp_inventata", "Bearer gunoi"])
def test_fara_cheie_valida_da_401(
    client: TestClient, agency_settings: Tenant, authorization: str | None
) -> None:
    headers = dict(MCP_HEADERS)
    if authorization:
        headers["Authorization"] = authorization
    response = client.post(
        STREAM, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 401


def test_serverul_merge_si_pe_stdio_pentru_aplicatiile_locale(tmp_path: Path) -> None:
    """Claude Desktop / Claude Code pornesc serverul ca proces: contul vine din mediu."""
    database = tmp_path / "stdio.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(name="Agentie", api_key_hash="x")
        session.add(tenant)
        session.commit()
        account = ClientAccount(tenant_id=tenant.id or 0, name="Client Stdio")
        session.add(account)
        session.commit()
        account_id = account.id
    engine.dispose()

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ppc_agent_server.mcp_server"],
        cwd=str(ROOT),
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "MCP_CLIENT_ACCOUNT_ID": str(account_id),
        },
    )

    async def talk() -> dict[str, Any]:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as mcp:
            await mcp.initialize()
            result = await mcp.call_tool("get_budget_summary", {})
            return dict(result.structured_content or {})

    summary = asyncio.run(talk())
    assert summary["client"] == "Client Stdio"
    assert summary["daily_cap"] == "50.00"
