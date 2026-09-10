"""Implementari ``mock`` deterministice ale furnizorilor.

Datele sunt generate in cod (determinist, fara retea). Modulul 3 va adauga aici
si furnizorul Meta Marketing.
"""

from __future__ import annotations

from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.providers.mock.crawler import MockCrawlerProvider
from ppc_agent.providers.mock.google import (
    MockGbpProvider,
    MockGscProvider,
    MockKeywordPlannerProvider,
)

__all__ = [
    "MockCrawlerProvider",
    "MockGbpProvider",
    "MockGoogleAdsProvider",
    "MockGscProvider",
    "MockKeywordPlannerProvider",
]
