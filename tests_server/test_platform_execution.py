"""Google Ads, TikTok si ChatGPT: propunerile aprobate se aplica, ca la Meta.

Motorul cu provideri dubli (fara retea), ruta de aprobare cu fabrica inlocuita:
schimbarea pleaca doar in mod live, cu contul conectat si moneda in lei.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.errors import ProviderError, SpendLimitExceeded
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.services.execution_engine import execute_proposal, resolve_target
from ppc_agent_server.models import ChangeOp, ChangeStatus, ProposedChange
from tests_server.test_proposal_execution import (  # noqa: F401 - hitl e fixture
    _CAP,
    _add_pending,
    _proposal,
    hitl,
)


class _FakePlatform:
    """Mutatiile oricarei platforme noi: retine ce i s-a cerut."""

    def __init__(
        self,
        *,
        currency: str = "RON",
        current_budget: Decimal | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.currency = currency
        self.current_budget = current_budget
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []

    def _record(self, *call: str) -> None:
        if self.fail:
            raise self.fail
        self.calls.append(call)

    async def account_currency(self) -> str:
        return self.currency

    async def current_daily_budget(self, object_id: str) -> Decimal | None:
        return self.current_budget

    async def update_campaign_budget(self, campaign_id: str, amount: Decimal) -> None:
        self._record("budget", campaign_id, str(amount))

    async def update_adgroup_budget(self, adgroup_id: str, amount: Decimal) -> None:
        self._record("budget", adgroup_id, str(amount))

    async def pause_campaign(self, campaign_id: str) -> None:
        self._record("pause", campaign_id)

    async def pause_adgroup(self, adgroup_id: str) -> None:
        self._record("pause", adgroup_id)

    async def pause_ad(self, ad_id: str) -> None:
        self._record("pause_ad", ad_id)

    async def add_negative_keyword(self, text: str, match_type: str) -> None:
        self._record("negative", text, match_type)


def _run(proposal: ProposedChange, provider: _FakePlatform, cap: Decimal = _CAP) -> bool:
    result = execute_proposal(proposal, provider, current_status="pending", max_daily_spend=cap)
    assert not result.error, result.error
    return result.executed


@pytest.mark.parametrize(
    ("resource", "resource_type", "platform", "kind", "object_id"),
    [
        ("tiktok_ad/77", "ad", "tiktok", "ad", "77"),
        ("chatgpt_campaign/cmpn_101", "campaign", "chatgpt", "campaign", "cmpn_101"),
        (
            "negative_keyword/gratuit",
            "negative_keyword",
            "google_ads",
            "negative_keyword",
            "gratuit",
        ),
    ],
)
def test_the_new_resources_name_their_platform(
    resource: str, resource_type: str, platform: str, kind: str, object_id: str
) -> None:
    target = resolve_target(_proposal(resource=resource, resource_type=resource_type))
    assert (target.platform, target.kind, target.object_id) == (platform, kind, object_id)


@pytest.mark.parametrize(
    ("resource", "resource_type", "op", "expected"),
    [
        ("campaign/555", "campaign", ChangeOp.UPDATE, ("budget", "555", "40")),
        ("campaign/555", "campaign", ChangeOp.PAUSE, ("pause", "555")),
        ("tiktok_ad_group/9", "ad_group", ChangeOp.UPDATE, ("budget", "9", "40")),
        ("tiktok_ad_group/9", "ad_group", ChangeOp.PAUSE, ("pause", "9")),
        ("tiktok_ad/77", "ad", ChangeOp.PAUSE, ("pause_ad", "77")),
        ("chatgpt_campaign/cmpn_1", "campaign", ChangeOp.UPDATE, ("budget", "cmpn_1", "40")),
        ("chatgpt_campaign/cmpn_1", "campaign", ChangeOp.PAUSE, ("pause", "cmpn_1")),
    ],
)
def test_budgets_and_pauses_reach_the_right_platform(
    resource: str, resource_type: str, op: ChangeOp, expected: tuple[str, ...]
) -> None:
    provider = _FakePlatform()
    spend = "40" if op is ChangeOp.UPDATE else "0"
    proposal = _proposal(op=op, resource=resource, resource_type=resource_type, spend=spend)

    assert _run(proposal, provider)
    assert provider.calls == [expected]


def test_a_negative_keyword_goes_to_the_account_list_with_its_match_type() -> None:
    provider = _FakePlatform()
    proposal = _proposal(
        op=ChangeOp.CREATE, resource="negative_keyword/gratuit", resource_type="negative_keyword"
    )
    proposal.after = {"term": "gratuit", "match_type": "phrase"}

    assert _run(proposal, provider)
    assert provider.calls == [("negative", "gratuit", "phrase")]


def test_a_budget_above_the_cap_needs_the_platform_to_confirm_it_is_a_reduction() -> None:
    proposal = _proposal(
        op=ChangeOp.UPDATE, resource="campaign/555", resource_type="campaign", spend="80"
    )
    lowered = _FakePlatform(current_budget=Decimal("100"))
    assert _run(proposal, lowered, cap=Decimal("50"))
    assert lowered.calls == [("budget", "555", "80")]

    raised = _FakePlatform(current_budget=Decimal("60"))
    with pytest.raises(SpendLimitExceeded):
        execute_proposal(proposal, raised, current_status="pending", max_daily_spend=Decimal("50"))
    assert raised.calls == []


def test_a_platform_refusal_is_a_failed_result_not_an_exception() -> None:
    provider = _FakePlatform(fail=ProviderError("buget sub minimul TikTok"))
    proposal = _proposal(
        op=ChangeOp.UPDATE, resource="tiktok_ad_group/9", resource_type="ad_group", spend="5"
    )
    result = execute_proposal(proposal, provider, current_status="pending", max_daily_spend=_CAP)
    assert result.executed is False
    assert "buget sub minimul TikTok" in result.error


# --- ruta de aprobare ---------------------------------------------------------------


@pytest.fixture
def google_live(monkeypatch: pytest.MonkeyPatch) -> _FakePlatform:
    """Server live cu un cont Google Ads conectat (mutatiile inlocuite)."""
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    provider = _FakePlatform()
    monkeypatch.setattr(ProviderFactory, "google_ads_mutations", lambda self: provider)
    return provider


def test_an_approved_google_budget_is_applied(
    hitl: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
    google_live: _FakePlatform,
) -> None:
    client, headers, account_id = hitl
    proposal_id = _add_pending(
        session,
        account_id,
        op=ChangeOp.UPDATE,
        resource="campaign/555",
        resource_type="campaign",
        spend="40",
    )

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == ChangeStatus.EXECUTED.value
    assert google_live.calls == [("budget", "555", "40.00")]


def test_an_account_in_another_currency_is_not_touched(
    hitl: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
    google_live: _FakePlatform,
) -> None:
    """Un buget de 40 intr-un cont in euro ar fi de cinci ori plafonul in lei."""
    google_live.currency = "EUR"
    client, headers, account_id = hitl
    proposal_id = _add_pending(
        session,
        account_id,
        op=ChangeOp.UPDATE,
        resource="campaign/555",
        resource_type="campaign",
        spend="40",
    )

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert "EUR" in response.json()["detail"]
    assert google_live.calls == []
    change = session.get(ProposedChange, proposal_id)
    assert change is not None
    session.refresh(change)
    assert change.status is ChangeStatus.PENDING


def test_a_tiktok_account_that_is_not_connected_says_so(
    hitl: tuple[TestClient, dict[str, str], int],  # noqa: F811
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    client, headers, account_id = hitl
    proposal_id = _add_pending(
        session,
        account_id,
        op=ChangeOp.PAUSE,
        resource="tiktok_ad_group/9",
        resource_type="ad_group",
    )

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers)

    assert response.status_code == 409
    assert "contul TikTok nu e conectat" in response.json()["detail"]
