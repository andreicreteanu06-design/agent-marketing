"""Teste pentru maparea CampaignObjective -> payload Meta Marketing API (ODAX)."""

from __future__ import annotations

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.providers.meta_campaign import build_meta_campaign_payload


def test_sales_maps_to_outcome_sales_and_purchase_event() -> None:
    payload = build_meta_campaign_payload(CampaignObjective.SALES)
    assert payload["objective"] == "OUTCOME_SALES"
    assert payload["ad_set"]["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert payload["ad_set"]["promoted_object"]["custom_event_type"] == "PURCHASE"


def test_lead_gen_maps_to_outcome_leads_and_the_server_only_qualified_event() -> None:
    payload = build_meta_campaign_payload(CampaignObjective.LEAD_GEN)
    assert payload["objective"] == "OUTCOME_LEADS"
    assert payload["ad_set"]["optimization_goal"] == "OFFSITE_CONVERSIONS"
    # Nu LEAD: pe acela il trimite si pixelul, la orice formular.
    assert payload["ad_set"]["promoted_object"]["custom_event_type"] == "SUBMIT_APPLICATION"


def test_payload_is_a_fresh_dict_each_call_not_a_shared_reference() -> None:
    """Mutarea unui payload returnat nu trebuie sa afecteze apelurile viitoare."""
    first = build_meta_campaign_payload(CampaignObjective.SALES)
    first["ad_set"]["promoted_object"]["custom_event_type"] = "LEAD"  # type: ignore[typeddict-item]

    second = build_meta_campaign_payload(CampaignObjective.SALES)
    assert second["ad_set"]["promoted_object"]["custom_event_type"] == "PURCHASE"
