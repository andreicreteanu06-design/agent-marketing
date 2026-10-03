"""Serverul MCP: uneltele si poarta de autentificare a conexiunii.

Uneltele se apeleaza direct prin ``call_tool`` - transportul SSE e cod al
SDK-ului, nu al nostru, si nu se re-testeaza aici. Ce se testeaza e ce am
promis: scoparea pe clientul conexiunii si faptul ca unealta de "scriere" NU
scrie in contul de reclame.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from sqlmodel import Session, select

from ppc_agent_server.mcp.server import (
    NotAuthenticatedError,
    build_server,
    current_client_account_id,
    reset_client_account_id,
    set_client_account_id,
)
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    SearchTermConversion,
    SerpPosition,
    SerpSource,
    Tenant,
)
from ppc_agent_server.settings import get_server_settings


def _call(name: str, **arguments: Any) -> dict[str, Any]:
    """Apeleaza o unealta si intoarce continutul ei structurat."""
    result = asyncio.run(build_server().call_tool(name, arguments))
    payload = getattr(result, "structured_content", None)
    if payload is not None:
        return dict(payload)
    return dict(json.loads(result.content[0].text))  # type: ignore[union-attr]


@pytest.fixture
def account(session: Session) -> ClientAccount:
    tenant = Tenant(name="Agentie MCP", api_key_hash="x")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    client_account = ClientAccount(tenant_id=tenant.id, name="Client MCP")
    session.add(client_account)
    session.commit()
    session.refresh(client_account)
    return client_account


@pytest.fixture
def connected(account: ClientAccount):  # type: ignore[no-untyped-def]
    """Simuleaza o conexiune MCP autentificata pentru ``account``."""
    token = set_client_account_id(account.id or 0)
    yield account
    reset_client_account_id(token)


def _seed(session: Session, account_id: int, term: str, rank: float, cost: str) -> None:
    now = datetime.now(tz=UTC)
    session.add(
        SerpPosition(
            client_account_id=account_id,
            checked_on=now,
            keyword=term,
            domain="exemplu.ro",
            source=SerpSource.OPENSERP,
            rank=rank,
        )
    )
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=now - timedelta(days=1),
            search_term=term,
            clicks=10,
            cost=Decimal(cost),
            conversions=5.0,
            conversions_value=Decimal("1000"),
        )
    )
    session.commit()


def test_cele_patru_unelte_sunt_expuse_cu_scheme_generate() -> None:
    """Schemele vin din adnotarile de tip - scrise de mana s-ar desincroniza."""
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    assert set(tools) == {
        "get_cannibalization_insights",
        "get_seo_opportunities",
        "get_budget_summary",
        "propose_budget_change",
    }
    schema = tools["propose_budget_change"].input_schema or {}
    assert set(schema.get("required", [])) == {"keyword", "proposed_daily_budget", "rationale"}


def test_unealta_fara_conexiune_autentificata_refuza() -> None:
    """Contul nu e parametru, deci fara conexiune legata nu se poate citi nimic."""
    with pytest.raises(NotAuthenticatedError):
        current_client_account_id()


def test_canibalizarea_vede_doar_clientul_conexiunii(
    connected: ClientAccount, session: Session
) -> None:
    account_id = connected.id or 0
    _seed(session, account_id, "service auto", rank=1.0, cost="1500")
    _seed(session, account_id + 999, "al altui client", rank=1.0, cost="9999")

    body = _call("get_cannibalization_insights")
    assert [item["term"] for item in body["items"]] == ["service auto"]
    assert body["total_potential_saving"] == "1500.00"


def test_oportunitatile_raporteaza_golurile(
    connected: ClientAccount, session: Session
) -> None:
    _seed(session, connected.id or 0, "schimb ulei", rank=45.0, cost="300")
    body = _call("get_seo_opportunities")
    assert [item["term"] for item in body["items"]] == ["schimb ulei"]


def test_propunerea_de_buget_nu_aplica_nimic(
    connected: ClientAccount, session: Session
) -> None:
    """Contractul central al uneltei: creeaza o propunere in asteptare, atat."""
    body = _call(
        "propose_budget_change",
        keyword="service auto",
        proposed_daily_budget=120.5,
        rationale="pozitia 1 organic, CPA in crestere",
    )
    assert body["applied"] is False
    assert body["status"] == ChangeStatus.PENDING.value

    change = session.exec(
        select(ProposedChange).where(ProposedChange.id == body["proposed_change_id"])
    ).one()
    assert change.status is ChangeStatus.PENDING
    assert change.client_account_id == connected.id
    assert change.after == {"daily_budget": "120.5"}
    assert change.source_module.startswith("mcp:")


def test_bugetul_negativ_e_refuzat(connected: ClientAccount) -> None:
    """ToolError, nu o exceptie oarecare: stratul de protocol o traduce intr-un
    rezultat de eroare pe care agentul il poate citi si corecta."""
    with pytest.raises(ToolError, match="negativ"):
        asyncio.run(
            build_server().call_tool(
                "propose_budget_change",
                {"keyword": "x", "proposed_daily_budget": -5, "rationale": "y"},
            )
        )


def test_sumarul_de_buget_citeste_datele_reale_ale_clientului(
    connected: ClientAccount, session: Session
) -> None:
    """Plafonul efectiv, ce e angajat (executat + in curs), ce mai incape, ce asteapta."""
    for index, (status, spend) in enumerate(
        (
            (ChangeStatus.EXECUTED, "20"),
            (ChangeStatus.APPROVED, "5"),
            (ChangeStatus.PENDING, "8"),
            (ChangeStatus.REJECTED, "99"),
        )
    ):
        session.add(
            ProposedChange(
                client_account_id=connected.id or 0,
                op=ChangeOp.UPDATE,
                resource=f"meta_ad_set/{index}",  # seturi diferite: bugetele se aduna
                resource_type="ad_set",
                projected_daily_spend=Decimal(spend),
                rationale="test",
                source_module="test",
                status=status,
            )
        )
    session.commit()

    assert _call("get_budget_summary") == {
        "client": "Client MCP",
        "currency": "RON",
        "daily_cap": "50.00",
        "committed_daily_budget": "25.00",
        "remaining_daily_budget": "25.00",
        "pending_proposals": 1,
        "pending_daily_budget": "8.00",
    }


def test_sumarul_de_buget_nu_trece_peste_plafonul_platformei(
    connected: ClientAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limita clientului e 50, dar MAX_DAILY_SPEND_RON=30: plafonul efectiv e 30."""
    monkeypatch.setenv("MAX_DAILY_SPEND_RON", "30")
    get_server_settings.cache_clear()
    assert _call("get_budget_summary")["daily_cap"] == "30"


# --- poarta de autentificare a transportului --------------------------------


def test_sse_fara_token_da_401(client: TestClient) -> None:
    assert client.get("/api/v1/mcp/sse").status_code == 401


def test_messages_fara_token_da_401(client: TestClient) -> None:
    assert client.post("/api/v1/mcp/messages", json={}).status_code == 401
