"""Teste pentru stub-ul live al Generative Engine Ads (ChatGPT) si BaseMarketingProvider."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers.base import BaseMarketingProvider
from ppc_agent.providers.live import LiveGenerativeEngineProvider


def test_is_a_base_marketing_provider() -> None:
    assert isinstance(LiveGenerativeEngineProvider(), BaseMarketingProvider)


def test_get_campaign_metrics_raises_setup_required() -> None:
    with pytest.raises(SetupRequiredError, match="OpenAI Ads"):
        LiveGenerativeEngineProvider().get_campaign_metrics("acc-1")


def test_scale_budget_raises_setup_required() -> None:
    with pytest.raises(SetupRequiredError, match="OpenAI Ads"):
        LiveGenerativeEngineProvider().scale_budget("campaign-1", Decimal("25.00"))


def test_pause_ad_raises_setup_required() -> None:
    with pytest.raises(SetupRequiredError, match="OpenAI Ads"):
        LiveGenerativeEngineProvider().pause_ad("ad-1")


def test_base_marketing_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseMarketingProvider()  # type: ignore[abstract]
