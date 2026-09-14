"""Teste pentru run_alignment() - in special rezolvarea ID-ului de cont Meta."""

from __future__ import annotations

import pytest

from ppc_agent.alignment.pipeline import run_alignment
from ppc_agent.config import AppConfig, Settings
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider


def test_run_alignment_uses_configured_meta_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cand meta_ad_account_id e configurat (relevant in mod live), run_alignment
    il trimite providerului in loc de placeholder-ul mock hardcodat."""
    captured: dict[str, str] = {}
    original = MockMetaMarketingProvider.ad_sets

    def spy(self: MockMetaMarketingProvider, ad_account_id: str):  # type: ignore[no-untyped-def]
        captured["meta"] = ad_account_id
        return original(self, ad_account_id)

    monkeypatch.setattr(MockMetaMarketingProvider, "ad_sets", spy)

    config = AppConfig(settings=Settings(_env_file=None, meta_ad_account_id="act_real_789"))
    factory = ProviderFactory(config)
    run_alignment(factory, config)

    assert captured["meta"] == "act_real_789"


def test_run_alignment_falls_back_to_placeholder_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comportament neschimbat: fara ID configurat, se foloseste placeholder-ul mock."""
    captured: dict[str, str] = {}
    original = MockMetaMarketingProvider.ad_sets

    def spy(self: MockMetaMarketingProvider, ad_account_id: str):  # type: ignore[no-untyped-def]
        captured["meta"] = ad_account_id
        return original(self, ad_account_id)

    monkeypatch.setattr(MockMetaMarketingProvider, "ad_sets", spy)

    config = AppConfig(settings=Settings(_env_file=None))
    factory = ProviderFactory(config)
    run_alignment(factory, config)

    assert captured["meta"] == "mock-account"
