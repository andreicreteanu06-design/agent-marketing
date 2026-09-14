"""Teste pentru enum-ul CampaignObjective."""

from __future__ import annotations

from ppc_agent.campaign_objective import CampaignObjective


def test_values_match_spec() -> None:
    assert CampaignObjective.SALES == "sales"
    assert CampaignObjective.LEAD_GEN == "lead_generation"


def test_is_str_enum_for_sqlmodel_and_json() -> None:
    assert isinstance(CampaignObjective.SALES, str)
