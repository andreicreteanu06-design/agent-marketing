"""Test end-to-end pentru comanda ``plan`` (Kelly + Thompson + Markov) pe mock."""

from __future__ import annotations

from decimal import Decimal

import pytest
from typer.testing import CliRunner

from ppc_agent.cli import app
from ppc_agent.config import AppConfig, BudgetConfig, Settings
from ppc_agent.decision.pipeline import run_plan
from ppc_agent.guardrails.spend_limiter import HARD_CEILING
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider
from ppc_agent.providers.mock.tiktok import MockTikTokAdsProvider

runner = CliRunner()


def test_plan_command_runs_and_prints_sections() -> None:
    result = runner.invoke(app, ["plan"])
    assert result.exit_code == 0
    for section in (
        "Dimensionare Kelly",
        "Alocare buget",
        "Thompson Sampling",
        "Atribuire Markov",
        "efect eliminare",
        "last-click",
        "Quality Score",
        "Lichiditate Meta",
        "platforma",
    ):
        assert section in result.output


def test_forecast_flag_is_noop_in_mock_mode() -> None:
    """--forecast cere mod live (alegere explicita) - in mod mock (implicit),
    doar informeaza si continua identic cu 'plan' fara flag."""
    baseline = runner.invoke(app, ["plan"])
    forecasted = runner.invoke(app, ["plan", "--forecast"])

    assert forecasted.exit_code == 0
    assert "--forecast cere mod live" in forecasted.output
    assert "Dimensionare Kelly" in forecasted.output

    # Acelasi plafon Kelly in ambele cazuri - --forecast n-a schimbat nimic in mock.
    def _cap_line(output: str) -> str:
        return next(line for line in output.splitlines() if "plafon:" in line)

    assert _cap_line(baseline.output) == _cap_line(forecasted.output)


def test_plan_budget_allocations_sum_to_kelly_sized_cap() -> None:
    config = AppConfig(settings=Settings(_env_file=None))
    config.budget.max_daily_spend = Decimal("37.00")
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)

    total = sum(
        (allocation.daily_budget for allocation in plan.budget_plan.allocations),
        Decimal("0"),
    )
    assert total == plan.budget_plan.daily_budget == plan.kelly.sized_daily_cap
    assert plan.kelly.sized_daily_cap <= HARD_CEILING


def test_kelly_disabled_keeps_baseline_cap() -> None:
    config = AppConfig(settings=Settings(_env_file=None))
    config.budget.max_daily_spend = Decimal("37.00")
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000, kelly_fraction=0.0)

    assert plan.kelly.sized_daily_cap == Decimal("37.00")
    assert plan.budget_plan.daily_budget == Decimal("37.00")


def test_positive_edge_scales_cap_above_baseline() -> None:
    # Datele mock au ROAS de cont > 1 -> Half-Kelly ridica plafonul peste baseline. Cu
    # vanzari pe trei platforme, doar cand comenzile magazinului confirma venitul.
    config = AppConfig(
        settings=Settings(_env_file=None),
        budget=BudgetConfig(shop_revenue=Decimal("1000000")),
    )
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)

    assert plan.kelly.edge == "pozitiv"
    assert plan.kelly.account_roas > 1.0
    assert plan.kelly.sized_daily_cap > plan.kelly.baseline_cap
    assert plan.kelly.sized_daily_cap <= HARD_CEILING


def test_sales_on_several_platforms_without_shop_orders_do_not_raise_the_cap() -> None:
    """Google, TikTok si Meta raporteaza fiecare vanzarile ei: suma poate numara aceeasi
    vanzare de doua ori. Fara comenzile magazinului, Kelly poate taia, dar nu creste."""
    config = AppConfig(settings=Settings(_env_file=None))
    plan = run_plan(ProviderFactory(config), config, n_samples=4000)

    assert plan.kelly.edge == "pozitiv"
    assert plan.kelly.sized_daily_cap == plan.kelly.baseline_cap
    assert "aceeasi vanzare poate fi numarata de doua ori" in plan.kelly.rationale


def test_shop_orders_cap_the_revenue_the_platforms_claim() -> None:
    """Platformele isi atribuie mai mult decat a vandut magazinul: ROAS-ul e pe comenzi."""
    claimed = run_plan(
        ProviderFactory(AppConfig(settings=Settings(_env_file=None))),
        AppConfig(settings=Settings(_env_file=None)),
        n_samples=2000,
    ).kelly.account_roas
    config = AppConfig(
        settings=Settings(_env_file=None), budget=BudgetConfig(shop_revenue=Decimal("100"))
    )
    plan = run_plan(ProviderFactory(config), config, n_samples=2000)

    assert plan.kelly.account_roas < claimed
    assert "plafonat la comenzile reale ale magazinului" in plan.kelly.rationale


def test_plan_is_reproducible() -> None:
    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    first = run_plan(factory, config, seed=7, n_samples=3000)
    second = run_plan(factory, config, seed=7, n_samples=3000)
    assert first.model_dump() == second.model_dump()


def test_plan_combines_google_tiktok_and_meta_arms() -> None:
    """Modulul 2 trateaza TikTok si Meta ca brate suplimentare, nu canale separate."""
    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)

    platforms = {allocation.platform for allocation in plan.budget_plan.allocations}
    assert platforms == {"google_ads", "tiktok_ads", "meta_ads"}

    google_arms = [a for a in plan.budget_plan.allocations if a.platform == "google_ads"]
    tiktok_arms = [a for a in plan.budget_plan.allocations if a.platform == "tiktok_ads"]
    meta_arms = [a for a in plan.budget_plan.allocations if a.platform == "meta_ads"]
    assert len(google_arms) == 5  # cele 5 campanii mock din providers/mock/ads.py
    assert len(tiktok_arms) == 4  # cele 4 grupuri mock din providers/mock/tiktok.py
    assert len(meta_arms) == 5  # cele 5 seturi de reclame mock din providers/mock/meta.py

    total = sum(
        (allocation.daily_budget for allocation in plan.budget_plan.allocations),
        Decimal("0"),
    )
    assert total == plan.budget_plan.daily_budget == plan.kelly.sized_daily_cap


def test_arm_capacity_absent_when_target_cpa_not_set() -> None:
    """Comportament neschimbat fata de sesiunile anterioare: target_cpa implicit None."""
    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)
    assert plan.arm_capacity is None


def test_arm_capacity_present_and_raises_floor_for_small_budget() -> None:
    """Buget mic + target_cpa mare -> pragul/brat calculat depaseste floor-ul static (5 lei)."""
    config = AppConfig(settings=Settings(_env_file=None))
    config.budget.max_daily_spend = Decimal("20.00")
    config.budget.target_cpa = Decimal("150.00")
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000, kelly_fraction=0.0)

    assert plan.arm_capacity is not None
    assert plan.arm_capacity.tier == "micro"
    assert plan.arm_capacity.recommended_max_concurrent_arms == 1
    assert plan.arm_capacity.recommended_min_arm_daily_spend > config.budget.min_arm_daily_spend

    funded = [a for a in plan.budget_plan.allocations if a.daily_budget > 0]
    assert len(funded) == 1  # floor-ul ridicat forteaza concentrarea pe un singur brat


def test_manual_min_arm_daily_spend_floor_is_never_lowered() -> None:
    """Un floor manual deja mai mare decat cel calculat nu trebuie coborat."""
    config = AppConfig(settings=Settings(_env_file=None))
    config.budget.min_arm_daily_spend = Decimal("999.00")
    config.budget.target_cpa = Decimal("10.00")  # ar recomanda un prag mult mai mic
    factory = ProviderFactory(config)
    plan = run_plan(factory, config, n_samples=4000)

    assert plan.arm_capacity is not None
    assert plan.arm_capacity.recommended_min_arm_daily_spend < config.budget.min_arm_daily_spend
    funded = [a for a in plan.budget_plan.allocations if a.daily_budget > 0]
    assert len(funded) == 1  # floor-ul manual (999) domina, ramane un singur brat finantat


def test_run_plan_uses_configured_account_ids_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cand ID-urile de cont sunt configurate (relevant in mod live), run_plan
    le trimite providerilor in loc de placeholder-ele mock hardcodate."""
    captured: dict[str, str] = {}

    original_google = MockGoogleAdsProvider.campaign_performance
    original_tiktok = MockTikTokAdsProvider.campaign_performance
    original_meta = MockMetaMarketingProvider.campaign_performance

    def spy_google(self: MockGoogleAdsProvider, customer_id: str):  # type: ignore[no-untyped-def]
        captured["google"] = customer_id
        return original_google(self, customer_id)

    def spy_tiktok(self: MockTikTokAdsProvider, advertiser_id: str):  # type: ignore[no-untyped-def]
        captured["tiktok"] = advertiser_id
        return original_tiktok(self, advertiser_id)

    def spy_meta(self: MockMetaMarketingProvider, ad_account_id: str):  # type: ignore[no-untyped-def]
        captured["meta"] = ad_account_id
        return original_meta(self, ad_account_id)

    monkeypatch.setattr(MockGoogleAdsProvider, "campaign_performance", spy_google)
    monkeypatch.setattr(MockTikTokAdsProvider, "campaign_performance", spy_tiktok)
    monkeypatch.setattr(MockMetaMarketingProvider, "campaign_performance", spy_meta)

    settings = Settings(
        _env_file=None,
        google_ads_customer_id="acct_real_123",
        tiktok_advertiser_id="adv_real_456",
        meta_ad_account_id="act_real_789",
    )
    config = AppConfig(settings=settings)
    factory = ProviderFactory(config)
    run_plan(factory, config, n_samples=1000)

    assert captured == {
        "google": "acct_real_123",
        "tiktok": "adv_real_456",
        "meta": "act_real_789",
    }


def test_run_plan_falls_back_to_placeholders_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comportament neschimbat: fara ID-uri configurate, se folosesc placeholder-ele mock."""
    captured: dict[str, str] = {}
    original_google = MockGoogleAdsProvider.campaign_performance

    def spy_google(self: MockGoogleAdsProvider, customer_id: str):  # type: ignore[no-untyped-def]
        captured["google"] = customer_id
        return original_google(self, customer_id)

    monkeypatch.setattr(MockGoogleAdsProvider, "campaign_performance", spy_google)

    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    run_plan(factory, config, n_samples=1000)

    assert captured["google"] == "mock-customer"
