"""Furnizor ``mock`` pentru Meta Marketing API: seturi de reclame.

Date fixe, alese ca sa exercite consolidarea: patru seturi micro-segmentate,
sub prag, in doua grupuri de audienta, plus unul deja sanatos.

Aceleasi cinci seturi de reclame alimenteaza acum si Modulul 2 (bandit,
``campaign_performance``/``conversion_paths``) — ``clicks``/``revenue`` sunt
literali noi per set (Insights API nu expune asta la ``ad_sets``), iar
``conversions``/``cost`` de acolo se deriva din ``weekly_conversions``/
``weekly_spend`` * ``_PERIOD_WEEKS`` ca sa nu existe doua surse ale adevarului
pentru acelasi cont.
"""

from __future__ import annotations

import random
from typing import NamedTuple

import pandas as pd

from ppc_agent.providers.base import MetaMarketingProvider


class _MetaAdSet(NamedTuple):
    ad_set_id: str
    name: str
    audience_def: str
    weekly_conversions: float
    weekly_spend: float
    learning_phase: bool
    clicks: int  # pe _PERIOD_WEEKS saptamani, doar pentru campaign_performance()
    revenue: float  # pe _PERIOD_WEEKS saptamani, doar pentru campaign_performance()


_AD_SETS: tuple[_MetaAdSet, ...] = (
    _MetaAdSet(
        ad_set_id="as_pfa_tanar",
        name="PFA 25-34",
        audience_def="pfa freelancer facturi 25 34",
        weekly_conversions=12.0,
        weekly_spend=180.0,
        learning_phase=True,
        clicks=1400,
        revenue=2100.0,
    ),
    _MetaAdSet(
        ad_set_id="as_pfa_matur",
        name="PFA 35-44",
        audience_def="pfa freelancer facturi 35 44",
        weekly_conversions=14.0,
        weekly_spend=210.0,
        learning_phase=True,
        clicks=1650,
        revenue=2500.0,
    ),
    _MetaAdSet(
        ad_set_id="as_srl_mic",
        name="SRL mic",
        audience_def="srl facturi contabilitate firma mica",
        weekly_conversions=13.0,
        weekly_spend=240.0,
        learning_phase=True,
        clicks=1550,
        revenue=2200.0,
    ),
    _MetaAdSet(
        ad_set_id="as_srl_startup",
        name="SRL startup",
        audience_def="srl startup facturi firma tech",
        weekly_conversions=12.0,
        weekly_spend=160.0,
        learning_phase=True,
        clicks=1300,
        revenue=1450.0,
    ),
    _MetaAdSet(
        ad_set_id="as_brand",
        name="Retargeting brand",
        audience_def="vizitatori site brand facturarepro",
        weekly_conversions=74.0,
        weekly_spend=300.0,
        learning_phase=False,
        clicks=2600,
        revenue=9200.0,
    ),
)
_PERIOD_WEEKS = 4.0

_CHANNELS: tuple[str, ...] = (
    "PFA 25-34",
    "PFA 35-44",
    "SRL mic",
    "SRL startup",
    "Retargeting brand",
)

# Probabilitatea de a converti un parcurs, in functie de canalele prezente —
# retargeting-ul domina clar, ca la CVR-ul observat in campaign_performance().
_CHANNEL_LIFT: dict[str, float] = {
    "PFA 25-34": 0.10,
    "PFA 35-44": 0.11,
    "SRL mic": 0.10,
    "SRL startup": 0.09,
    "Retargeting brand": 0.30,
}
_BASE_CONVERT_PROB = 0.04
_N_PATHS = 400
_SEED = 20260301


class MockMetaMarketingProvider(MetaMarketingProvider):
    """Meta Marketing simulat pentru dezvoltare si teste."""

    def ad_sets(self, ad_account_id: str) -> pd.DataFrame:
        """Returneaza tabelul fix de seturi de reclame."""
        rows = [
            {
                "ad_set_id": ad_set.ad_set_id,
                "name": ad_set.name,
                "audience_def": ad_set.audience_def,
                "weekly_conversions": ad_set.weekly_conversions,
                "weekly_spend": ad_set.weekly_spend,
                "learning_phase": ad_set.learning_phase,
                "learning_status": "LEARNING" if ad_set.learning_phase else "SUCCESS",
                # bugetul de acum = cheltuiala medie pe zi, ca o singura sursa a adevarului
                "daily_budget": round(ad_set.weekly_spend / 7, 2),
            }
            for ad_set in _AD_SETS
        ]
        return pd.DataFrame(rows)

    def campaign_performance(self, ad_account_id: str) -> pd.DataFrame:
        """Returneaza aceleasi seturi de reclame, agregate pe 4 saptamani pentru bandit."""
        rows = [
            {
                "arm_id": ad_set.ad_set_id,
                "name": ad_set.name,
                "clicks": ad_set.clicks,
                "conversions": round(ad_set.weekly_conversions * _PERIOD_WEEKS),
                "cost": ad_set.weekly_spend * _PERIOD_WEEKS,
                "revenue": ad_set.revenue,
            }
            for ad_set in _AD_SETS
        ]
        return pd.DataFrame(rows)

    def conversion_paths(self, ad_account_id: str) -> list[list[str]]:
        """Genereaza ``_N_PATHS`` parcursuri deterministe pe cele cinci seturi de reclame."""
        rng = random.Random(f"{_SEED}:{ad_account_id}")
        paths: list[list[str]] = []
        for _ in range(_N_PATHS):
            length = rng.choices((1, 2, 3), weights=(0.5, 0.35, 0.15))[0]
            touchpoints = [rng.choice(_CHANNELS) for _ in range(length)]
            lift = max(_CHANNEL_LIFT[channel] for channel in touchpoints)
            converted = rng.random() < min(0.9, _BASE_CONVERT_PROB + lift)
            paths.append([*touchpoints, "conversion" if converted else "null"])
        return paths
