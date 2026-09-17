"""Teste pentru utilitarele din decision/pipeline.py care nu sunt ``run_plan`` insusi
(vezi test_plan_cli.py pentru run_plan/CLI) - in special detectia providerilor
care suporta raportare zilnica (``SupportsDailyPerformance``, folosita de
``--forecast`` in CLI)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from ppc_agent.decision.pipeline import SupportsDailyPerformance, collect_daily_histories
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
