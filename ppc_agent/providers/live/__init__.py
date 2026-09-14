"""Furnizorii ``live``.

Google/Meta/TikTok Ads (performanta pentru bandit + lichiditate Meta) au
implementari reale — vezi ``google_ads.py``/``meta.py``/``tiktok.py``, acelasi
pattern ca :class:`ppc_agent.copywriter.llm.LiveLLMClient` (httpx simplu,
testabil cu ``httpx.MockTransport``). Restul (crawler, Google Search Console,
Google Business Profile, Keyword Planner — Modulul 1) raman stub-uri: fiecare
metoda ridica :class:`ppc_agent.errors.SetupRequiredError`, niciun apel de
retea nu este efectuat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers import base
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "LiveCrawlerProvider",
    "LiveGbpProvider",
    "LiveGoogleAdsProvider",
    "LiveGscProvider",
    "LiveKeywordPlannerProvider",
    "LiveMetaMarketingProvider",
    "LiveTikTokAdsProvider",
]

_SETUP_HINT = (
    "Modul 'live' indisponibil pentru acest furnizor: clientul real de API nu "
    "e inca implementat. Ruleaza cu PPC_PROVIDER_MODE=mock sau asteapta "
    "integrarea live (Modulul 1)."
)


def _not_ready() -> NoReturn:
    """Ridica intotdeauna :class:`SetupRequiredError` cu instructiuni de configurare."""
    raise SetupRequiredError(_SETUP_HINT)


class LiveCrawlerProvider(base.CrawlerProvider):
    """Stub live pentru crawling-ul domeniului.

    Integrarea reala (Playwright cu fallback httpx + BeautifulSoup, plus
    descarcarea ``robots.txt``) ramane pentru o faza ulterioara.
    """

    def fetch(self, url: str) -> base.FetchResult:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _not_ready()

    def robots_txt(self, base_url: str) -> str | None:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveGscProvider(base.GscProvider):
    """Stub live pentru Google Search Console."""

    def top_queries(
        self, site_url: str, days: int = 90, min_impressions: int = 100
    ) -> pd.DataFrame:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveGbpProvider(base.GbpProvider):
    """Stub live pentru Google Business Profile."""

    def local_signals(self, location_id: str) -> dict[str, object]:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveKeywordPlannerProvider(base.KeywordPlannerProvider):
    """Stub live pentru Google Keyword Planner."""

    def expand(self, seeds: list[str], geo: str, language: str) -> pd.DataFrame:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _not_ready()
