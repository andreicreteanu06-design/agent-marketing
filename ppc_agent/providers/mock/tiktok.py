"""Furnizor ``mock`` pentru TikTok Ads: performanta grupurilor de anunturi + parcursuri.

Aceeasi structura ca :mod:`ppc_agent.providers.mock.ads` (Google): date fixe plus
un singur ``random.Random`` cu seed fix pentru parcursuri. Fara apeluri de retea.
``arm_id``-urile au prefixul ``tt_`` ca sa nu se cioceasca niciodata cu ``c_``-urile
Google Ads cand cele doua seturi de brate se combina in Modulul 2.
"""

from __future__ import annotations

import random

import pandas as pd

from ppc_agent.providers.base import TikTokAdsProvider

_AD_GROUPS: tuple[tuple[str, str, int, int, float, float], ...] = (
    # arm_id, nume, click-uri, conversii, cost, venit
    ("tt_spark", "Spark Ads - UGC", 3200, 145, 1800.0, 3200.0),
    ("tt_infeed", "In-Feed - Conversii", 5100, 210, 2600.0, 5450.0),
    ("tt_topview", "TopView - Awareness", 8900, 62, 3400.0, 1350.0),
    ("tt_collection", "Collection Ads - Catalog", 1900, 88, 900.0, 2100.0),
)

_CHANNELS: tuple[str, ...] = (
    "Spark Ads - UGC",
    "In-Feed - Conversii",
    "TopView - Awareness",
    "Collection Ads - Catalog",
)

# Probabilitatea de a converti un parcurs, in functie de canalele prezente.
_CHANNEL_LIFT: dict[str, float] = {
    "Spark Ads - UGC": 0.22,
    "In-Feed - Conversii": 0.16,
    "TopView - Awareness": 0.04,
    "Collection Ads - Catalog": 0.10,
}
_BASE_CONVERT_PROB = 0.04
_N_PATHS = 400
_SEED = 20260215


class MockTikTokAdsProvider(TikTokAdsProvider):
    """TikTok Ads simulat pentru dezvoltare si teste."""

    def campaign_performance(self, advertiser_id: str) -> pd.DataFrame:
        """Returneaza tabelul fix de performanta pe grupuri de anunturi."""
        rows = [
            {
                "arm_id": arm_id,
                "name": name,
                "clicks": clicks,
                "conversions": conversions,
                "cost": cost,
                "revenue": revenue,
            }
            for arm_id, name, clicks, conversions, cost, revenue in _AD_GROUPS
        ]
        return pd.DataFrame(rows)

    def conversion_paths(self, advertiser_id: str) -> list[list[str]]:
        """Genereaza ``_N_PATHS`` parcursuri deterministe pe cele patru canale."""
        rng = random.Random(f"{_SEED}:{advertiser_id}")
        paths: list[list[str]] = []
        for _ in range(_N_PATHS):
            length = rng.choices((1, 2, 3), weights=(0.5, 0.35, 0.15))[0]
            touchpoints = [rng.choice(_CHANNELS) for _ in range(length)]
            lift = max(_CHANNEL_LIFT[channel] for channel in touchpoints)
            converted = rng.random() < min(0.9, _BASE_CONVERT_PROB + lift)
            paths.append([*touchpoints, "conversion" if converted else "null"])
        return paths
