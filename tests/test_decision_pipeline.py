"""Teste pentru utilitarele din decision/pipeline.py care nu sunt ``run_plan`` insusi
(vezi test_plan_cli.py pentru run_plan/CLI) - in special detectia providerilor
care suporta raportare zilnica (``SupportsDailyPerformance``, folosita de
``--forecast`` in CLI)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from ppc_agent.config import AppConfig, ProviderMode, Settings
from ppc_agent.decision.kelly_sizing import size_daily_budget
from ppc_agent.decision.models import ArmStats
from ppc_agent.decision.pipeline import (
    SupportsDailyPerformance,
    arms_from_performance,
    collect_daily_histories,
    run_plan,
    value_unreported_conversions,
)
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider
from ppc_agent.providers.mock.tiktok import MockTikTokAdsProvider


class _FakeDailyProvider:
    """Stand-in minim - implementeaza doar metoda ceruta de protocol."""

    def daily_campaign_performance(self, account_id: str, *, days: int) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"arm_id": "a", "date": date(2026, 1, 1), "clicks": 10, "conversions": 1,
                 "cost": 5.0, "revenue": 20.0},
                {"arm_id": "a", "date": date(2026, 1, 2), "clicks": 12, "conversions": 2,
                 "cost": 5.0, "revenue": 40.0},
                {"arm_id": "b", "date": date(2026, 1, 1), "clicks": 30, "conversions": 0,
                 "cost": 8.0, "revenue": 0.0},
            ]
        )


class _ProviderWithoutDailySupport:
    """Nu implementeaza deloc metoda - reprezinta orice furnizor de azi (mock sau live)."""


def test_supports_daily_performance_is_a_runtime_checkable_protocol() -> None:
    assert isinstance(_FakeDailyProvider(), SupportsDailyPerformance)
    assert not isinstance(_ProviderWithoutDailySupport(), SupportsDailyPerformance)


@pytest.mark.parametrize(
    "provider",
    [MockGoogleAdsProvider(), MockTikTokAdsProvider(), MockMetaMarketingProvider()],
)
def test_no_current_mock_provider_implements_daily_performance(provider: object) -> None:
    """Deliberat: niciun mock nu fabrica date zilnice - vezi docstring-ul protocolului."""
    assert not isinstance(provider, SupportsDailyPerformance)


def test_collect_daily_histories_uses_only_supporting_providers() -> None:
    histories = collect_daily_histories(
        [
            (_FakeDailyProvider(), "acc-1"),
            (_ProviderWithoutDailySupport(), "acc-2"),
        ]
    )

    assert set(histories) == {"a", "b"}
    assert len(histories["a"]) == 2
    assert histories["a"][0].date == date(2026, 1, 1)
    assert histories["a"][0].clicks == 10
    assert histories["a"][0].conversions == 1
    assert histories["a"][0].cost == Decimal("5.0")
    assert histories["b"][0].revenue == Decimal("0.0")


def test_collect_daily_histories_returns_empty_when_nothing_supports_it() -> None:
    histories = collect_daily_histories([(_ProviderWithoutDailySupport(), "acc-1")])
    assert histories == {}


def test_live_plan_reads_only_the_configured_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pilot doar pe Meta: cheile Google/TikTok lipsa nu mai opresc planul de noapte."""
    settings = Settings(
        provider_mode=ProviderMode.LIVE, meta_access_token="t", meta_ad_account_id="act_1"
    )
    config = AppConfig(settings=settings)
    factory = ProviderFactory(config)
    monkeypatch.setattr(factory, "meta", MockMetaMarketingProvider)  # Meta "live", fara retea

    plan = run_plan(factory, config, n_samples=200)
    assert {item.platform for item in plan.budget_plan.allocations} == {"meta_ads"}


def test_lead_value_keeps_a_cheap_lead_account_from_being_halved() -> None:
    """40 de lead-uri la 25 lei, fara venit raportat: fara valoare, Kelly vede ROAS 0."""
    frame = pd.DataFrame(
        [{"arm_id": "a", "name": "a", "clicks": 800, "conversions": 40, "cost": 1000.0,
          "revenue": 0.0}]
    )

    def cap(lead_value: Decimal | None) -> Decimal:
        arms = arms_from_performance(frame, platform="meta_ads", lead_value=lead_value)
        kelly = size_daily_budget(arms, baseline_cap=Decimal("50"), hard_ceiling=Decimal("500"))
        return kelly.sized_daily_cap

    assert cap(None) == Decimal("25.00")  # bugetul taiat la jumatate
    assert cap(Decimal("80")) > Decimal("50")  # lead de 80 lei luat cu 25: merita mai mult


def test_paused_ad_sets_get_no_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un set oprit de om nu mai primeste buget: cota lui s-ar pierde, iar cele active
    ar primi mai putin decat le revine."""

    class _MetaWithPausedBrand(MockMetaMarketingProvider):
        def campaign_performance(self, ad_account_id: str) -> pd.DataFrame:
            frame = super().campaign_performance(ad_account_id)
            frame["active"] = frame["arm_id"] != "as_brand"
            return frame

    settings = Settings(
        provider_mode=ProviderMode.LIVE, meta_access_token="t", meta_ad_account_id="act_1"
    )
    config = AppConfig(settings=settings)
    factory = ProviderFactory(config)
    monkeypatch.setattr(factory, "meta", _MetaWithPausedBrand)

    plan = run_plan(factory, config, n_samples=200)
    funded = {item.arm_id for item in plan.budget_plan.allocations}
    assert funded and "as_brand" not in funded


# --- vanzarile raportate fara valoare (TikTok, Google fara urmarirea valorii) ----------


def _arm(arm_id: str, platform: str, conversions: int, revenue: str) -> ArmStats:
    return ArmStats(
        arm_id=arm_id,
        name=arm_id,
        clicks=200,
        conversions=conversions,
        cost=Decimal("100"),
        revenue=Decimal(revenue),
        platform=platform,
    )


def test_sales_reported_without_value_are_worth_the_real_average_order() -> None:
    meta = _arm("meta", "meta_ads", 5, "750")  # cos mediu real: 150
    tiktok = _arm("tiktok", "tiktok_ads", 4, "0")

    valued = value_unreported_conversions([meta, tiktok], fallback=Decimal("300"))

    assert valued[0] is meta
    assert valued[1].revenue == Decimal("600.00")


def test_before_five_valued_orders_the_expected_basket_is_used() -> None:
    valued = value_unreported_conversions(
        [_arm("meta", "meta_ads", 2, "300"), _arm("google", "google_ads", 3, "0")],
        fallback=Decimal("250"),
    )

    assert valued[1].revenue == Decimal("750.00")


def test_without_any_value_nothing_is_invented() -> None:
    arms = [_arm("tiktok", "tiktok_ads", 4, "0"), _arm("idle", "tiktok_ads", 0, "0")]

    assert value_unreported_conversions(arms, fallback=None) == arms
    # Un brat fara conversii ramane fara venit si cand exista o valoare.
    assert value_unreported_conversions(arms, fallback=Decimal("100"))[1].revenue == 0
