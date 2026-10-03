"""Pragul de profit din costurile clientului si raza reclamelor locale."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.client_economics import (
    EconomicsError,
    choose_radius,
    lead_thresholds,
    place_size,
    shop_thresholds,
)
from ppc_agent.providers.meta_campaign import MetaLaunchSpec, adset_fields


def test_a_shop_order_leaves_its_contribution_as_the_max_cac() -> None:
    """250 lei cos, 110 produse, 18 transport, 2% comision, 5% retururi:
    237,50 - 104,50 - 18 - 5 = 110 lei raman inainte de reclame."""
    limits = shop_thresholds(
        average_order_value=Decimal("250"),
        product_cost=Decimal("110"),
        shipping_cost=Decimal("18"),
        payment_fee_pct=Decimal("2"),
        return_rate_pct=Decimal("5"),
    )

    assert limits.max_cac == Decimal("110.00")
    assert limits.break_even_roas == Decimal("2.28")  # 250 / 110, rotunjit in sus
    assert limits.conversion_value == Decimal("250")
    assert limits.max_cpl is None


def test_a_shop_that_loses_money_before_ads_is_told_so() -> None:
    with pytest.raises(EconomicsError, match="înainte de reclame"):
        shop_thresholds(
            average_order_value=Decimal("100"),
            product_cost=Decimal("90"),
            shipping_cost=Decimal("15"),
            payment_fee_pct=Decimal("0"),
            return_rate_pct=Decimal("0"),
        )


def test_a_lead_is_worth_the_customer_profit_times_the_close_rate() -> None:
    limits = lead_thresholds(customer_profit=Decimal("600"), close_rate_pct=Decimal("30"))

    assert limits.max_cac == Decimal("600.00")
    assert limits.max_cpl == limits.conversion_value == Decimal("180.00")
    assert limits.break_even_roas == 1


def test_a_cafe_in_a_big_city_reaches_its_neighbourhood_not_the_whole_city() -> None:
    choice = choose_radius("zilnic", "oras_mare", None)
    assert choice.radius_km == 3
    assert "oraș mare" in choice.reason


def test_the_client_limit_is_the_ceiling_and_a_wider_wish_starts_smaller() -> None:
    assert choose_radius("programat", "oras", Decimal("5")).radius_km == 5
    wider = choose_radius("programat", "oras_mare", Decimal("30"))
    assert wider.radius_km == 6
    assert "Lărgesc raza" in wider.reason


def test_a_village_gets_a_wider_radius_and_meta_limits_hold() -> None:
    assert choose_radius("zilnic", "localitate_mica", None).radius_km == 10
    assert choose_radius("zilnic", "oras_mare", Decimal("0.3")).radius_km == 1


@pytest.mark.parametrize(
    ("population", "place_type", "expected"),
    [
        (320_000, "city", "oras_mare"),
        (45_000, "town", "oras"),
        (None, "village", "localitate_mica"),
    ],
)
def test_the_place_size_comes_from_population_or_its_type(
    population: int | None, place_type: str, expected: str
) -> None:
    assert place_size(population, place_type) == expected


def _spec(**overrides: object) -> MetaLaunchSpec:
    fields: dict[str, object] = {
        "campaign_name": "Service Cluj",
        "objective": CampaignObjective.LEAD_GEN,
        "daily_budget": Decimal("40"),
        "pixel_id": "123",
        "custom_event_type": "LEAD",
        "page_id": "456",
        "target_url": "https://service.ro",
        "headline": "Revizie azi",
        "primary_text": "Programeaza-te",
        "image_url": "https://service.ro/a.jpg",
        "country": "RO",
        "call_to_action": "LEARN_MORE",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)  # type: ignore[arg-type]


def test_a_local_launch_targets_a_radius_around_the_business() -> None:
    spec = _spec(
        latitude=Decimal("46.770439"), longitude=Decimal("23.591423"), radius_km=Decimal("6")
    )

    targeting = adset_fields(spec, campaign_id="1", daily_budget_minor=4000)["targeting"]

    assert '"custom_locations":[{"latitude":46.770439,"longitude":23.591423,"radius":6.0' in (
        targeting
    )
    assert '"distance_unit":"kilometer"' in targeting
    assert "countries" not in targeting
    assert MetaLaunchSpec.from_payload(spec.to_payload()) == spec


def test_a_national_launch_keeps_the_country_and_old_proposals_still_load() -> None:
    spec = _spec()
    payload = spec.to_payload()
    payload.pop("location")  # o propunere salvata inainte de zona locala

    assert MetaLaunchSpec.from_payload(payload) == spec
    assert (
        '"countries":["RO"]'
        in adset_fields(spec, campaign_id="1", daily_budget_minor=1)["targeting"]
    )


def test_a_radius_without_coordinates_or_beyond_meta_limits_is_refused() -> None:
    with pytest.raises(ValueError, match="toate trei"):
        _spec(radius_km=Decimal("5"))
    with pytest.raises(ValueError, match="intre 1 si 80"):
        _spec(latitude=Decimal("46"), longitude=Decimal("23"), radius_km=Decimal("120"))
