"""Furnizor ``mock`` pentru Google Ads: performanta campaniilor + parcursuri de conversie.

Datele sunt generate determinist (un singur ``random.Random`` cu seed fix). Fara
apeluri de retea. Parcursurile au structura suficienta pentru ca atribuirea Markov
sa produca efecte de eliminare distincte intre canale.
"""

from __future__ import annotations

import random

import pandas as pd

from ppc_agent.providers.base import GoogleAdsProvider

_CAMPAIGNS: tuple[tuple[str, str, int, int, float], ...] = (
    # arm_id, nume, click-uri, conversii, cost
    ("c_brand", "Search - Brand", 1200, 168, 900.0),
    ("c_generic", "Search - Generic", 4300, 215, 5400.0),
    ("c_pmax", "Performance Max", 2600, 130, 3100.0),
    ("c_display", "Display - Remarketing", 5200, 78, 1600.0),
    ("c_youtube", "YouTube - Awareness", 3800, 19, 2000.0),
)

_CHANNELS: tuple[str, ...] = (
    "Search - Brand",
    "Search - Generic",
    "Performance Max",
    "Display - Remarketing",
    "YouTube - Awareness",
)

# Probabilitatea de a converti un parcurs, in functie de canalele prezente.
_CHANNEL_LIFT: dict[str, float] = {
    "Search - Brand": 0.45,
    "Search - Generic": 0.18,
    "Performance Max": 0.15,
    "Display - Remarketing": 0.06,
    "YouTube - Awareness": 0.03,
}
_BASE_CONVERT_PROB = 0.05
_N_PATHS = 400
_SEED = 20260101


class MockGoogleAdsProvider(GoogleAdsProvider):
    """Google Ads simulat pentru dezvoltare si teste."""

    def campaign_performance(self, customer_id: str) -> pd.DataFrame:
        """Returneaza tabelul fix de performanta pe campanii."""
        rows = [
            {
                "arm_id": arm_id,
                "name": name,
                "clicks": clicks,
                "conversions": conversions,
                "cost": cost,
            }
            for arm_id, name, clicks, conversions, cost in _CAMPAIGNS
        ]
        return pd.DataFrame(rows)

    def conversion_paths(self, customer_id: str) -> list[list[str]]:
        """Genereaza ``_N_PATHS`` parcursuri deterministe pe cele cinci canale."""
        rng = random.Random(f"{_SEED}:{customer_id}")
        paths: list[list[str]] = []
        for _ in range(_N_PATHS):
            length = rng.choices((1, 2, 3, 4), weights=(0.35, 0.35, 0.2, 0.1))[0]
            touchpoints = [rng.choice(_CHANNELS) for _ in range(length)]
            lift = max(_CHANNEL_LIFT[channel] for channel in touchpoints)
            converted = rng.random() < min(0.9, _BASE_CONVERT_PROB + lift)
            paths.append([*touchpoints, "conversion" if converted else "null"])
        return paths
