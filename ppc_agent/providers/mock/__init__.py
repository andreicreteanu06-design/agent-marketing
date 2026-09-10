"""Implementari ``mock`` deterministice ale furnizorilor.

Datele sunt generate in cod (determinist, fara retea).
"""

from __future__ import annotations

from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.providers.mock.crawler import MockCrawlerProvider
from ppc_agent.providers.mock.google import (
    MockGbpProvider,
    MockGscProvider,
    MockKeywordPlannerProvider,
)
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider

__all__ = [
    "MockCrawlerProvider",
    "MockGbpProvider",
    "MockGoogleAdsProvider",
    "MockGscProvider",
    "MockKeywordPlannerProvider",
    "MockMetaMarketingProvider",
]
