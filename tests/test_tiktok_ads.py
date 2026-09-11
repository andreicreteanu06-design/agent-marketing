"""Teste pentru furnizorul mock TikTok Ads (performanta + parcursuri de conversie)."""

from __future__ import annotations

from ppc_agent.providers.mock.tiktok import MockTikTokAdsProvider

_ADVERTISER = "adv_mock"


def test_campaign_performance_is_deterministic() -> None:
    provider = MockTikTokAdsProvider()
    first = provider.campaign_performance(_ADVERTISER)
    second = provider.campaign_performance(_ADVERTISER)
    assert first.equals(second)


def test_campaign_performance_has_expected_columns_and_arm_id_prefix() -> None:
    provider = MockTikTokAdsProvider()
    frame = provider.campaign_performance(_ADVERTISER)
    assert set(frame.columns) == {"arm_id", "name", "clicks", "conversions", "cost", "revenue"}
    assert len(frame) >= 3
    assert all(arm_id.startswith("tt_") for arm_id in frame["arm_id"])


def test_arm_ids_never_collide_with_google_ads() -> None:
    """Prefixul tt_ garanteaza brate combinabile fara ciocnire cu c_ de la Google."""
    from ppc_agent.providers.mock.ads import MockGoogleAdsProvider

    google_ids = set(MockGoogleAdsProvider().campaign_performance("cust").arm_id)
    tiktok_ids = set(MockTikTokAdsProvider().campaign_performance(_ADVERTISER).arm_id)
    assert google_ids.isdisjoint(tiktok_ids)


def test_conversion_paths_are_deterministic() -> None:
    provider = MockTikTokAdsProvider()
    first = provider.conversion_paths(_ADVERTISER)
    second = provider.conversion_paths(_ADVERTISER)
    assert first == second


def test_conversion_paths_shape() -> None:
    provider = MockTikTokAdsProvider()
    paths = provider.conversion_paths(_ADVERTISER)
    assert len(paths) > 0
    for path in paths:
        assert path[-1] in ("conversion", "null")
        assert len(path) >= 2


def test_different_advertiser_ids_yield_different_paths() -> None:
    provider = MockTikTokAdsProvider()
    assert provider.conversion_paths("adv_a") != provider.conversion_paths("adv_b")
