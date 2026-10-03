"""Teste pentru enum-ul CampaignObjective."""

from __future__ import annotations

from decimal import Decimal

from ppc_agent.campaign_objective import CampaignObjective, break_even_roas, target_cpa


def test_values_match_spec() -> None:
    assert CampaignObjective.SALES == "sales"
    assert CampaignObjective.LEAD_GEN == "lead_generation"


def test_is_str_enum_for_sqlmodel_and_json() -> None:
    assert isinstance(CampaignObjective.SALES, str)


def test_a_shop_breaks_even_above_roas_one_until_its_margin_is_set() -> None:
    assert break_even_roas(CampaignObjective.SALES, None) == Decimal("2")  # marja 50%
    assert break_even_roas(CampaignObjective.LEAD_GEN, None) == Decimal("1")
    assert break_even_roas(CampaignObjective.SALES, Decimal("2.5")) == Decimal("2.5")


def test_target_cpa_comes_from_the_real_basket_once_there_are_enough_orders() -> None:
    # Cos mediu real 150 (3600 / 24), marja 40% -> cel mult 60 lei pe vanzare.
    assert target_cpa(
        Decimal("300"), Decimal("2.5"), revenue=Decimal("3600"), conversions=24
    ) == Decimal("60.00")
    # Prea putine vanzari: valoarea asteptata a clientului.
    assert target_cpa(
        Decimal("300"), Decimal("2.5"), revenue=Decimal("600"), conversions=2
    ) == Decimal("120.00")
