"""Furnizor ``mock`` pentru Meta Marketing API: seturi de reclame.

Date fixe, alese ca sa exercite consolidarea: patru seturi micro-segmentate,
sub prag, in doua grupuri de audienta, plus unul deja sanatos.
"""

from __future__ import annotations

import pandas as pd

from ppc_agent.providers.base import MetaMarketingProvider

_AD_SETS: tuple[tuple[str, str, str, float, float, bool], ...] = (
    # id, nume, audienta, conversii/sapt, cheltuiala/sapt, in invatare
    ("as_pfa_tanar", "PFA 25-34", "pfa freelancer facturi 25 34", 12.0, 180.0, True),
    ("as_pfa_matur", "PFA 35-44", "pfa freelancer facturi 35 44", 14.0, 210.0, True),
    ("as_srl_mic", "SRL mic", "srl facturi contabilitate firma mica", 13.0, 240.0, True),
    ("as_srl_startup", "SRL startup", "srl startup facturi firma tech", 12.0, 160.0, True),
    ("as_brand", "Retargeting brand", "vizitatori site brand facturarepro", 74.0, 300.0, False),
)


class MockMetaMarketingProvider(MetaMarketingProvider):
    """Meta Marketing simulat pentru dezvoltare si teste."""

    def ad_sets(self, ad_account_id: str) -> pd.DataFrame:
        """Returneaza tabelul fix de seturi de reclame."""
        rows = [
            {
                "ad_set_id": ad_set_id,
                "name": name,
                "audience_def": audience,
                "weekly_conversions": conversions,
                "weekly_spend": spend,
                "learning_phase": learning,
            }
            for ad_set_id, name, audience, conversions, spend, learning in _AD_SETS
        ]
        return pd.DataFrame(rows)
