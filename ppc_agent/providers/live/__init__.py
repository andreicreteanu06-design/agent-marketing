"""Stub-uri pentru furnizorii ``live``.

Pana la implementarea clientilor reali (Google Ads API, Google Search Console,
Google Business Profile, Keyword Planner, Meta Marketing API), fiecare metoda
ridica :class:`ppc_agent.errors.SetupRequiredError`. Niciun apel de retea nu este
efectuat in acest modul.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers import base

if TYPE_CHECKING:
    import pandas as pd

_SETUP_HINT = (
    "Modul 'live' indisponibil: clientii reali de API nu sunt inca implementati. "
    "Ruleaza cu PPC_PROVIDER_MODE=mock sau asteapta faza de integrare live."
)


def _not_ready() -> NoReturn:
    """Ridica intotdeauna :class:`SetupRequiredError` cu instructiuni de configurare."""
    raise SetupRequiredError(_SETUP_HINT)


class LiveCrawlerProvider(base.CrawlerProvider):
    """Stub live pentru crawling-ul domeniului.

    Integrarea reala (Playwright cu fallback httpx + BeautifulSoup, plus
    descarcarea ``robots.txt``) se adauga in faza de integrare live.
    """

    def fetch(self, url: str) -> base.FetchResult:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()

    def robots_txt(self, base_url: str) -> str | None:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveGscProvider(base.GscProvider):
    """Stub live pentru Google Search Console."""

    def top_queries(
        self, site_url: str, days: int = 90, min_impressions: int = 100
    ) -> pd.DataFrame:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveGbpProvider(base.GbpProvider):
    """Stub live pentru Google Business Profile."""

    def local_signals(self, location_id: str) -> dict[str, object]:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveKeywordPlannerProvider(base.KeywordPlannerProvider):
    """Stub live pentru Google Keyword Planner."""

    def expand(self, seeds: list[str], geo: str, language: str) -> pd.DataFrame:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveGoogleAdsProvider(base.GoogleAdsProvider):
    """Stub live pentru Google Ads API (performanta + parcursuri de conversie)."""

    def campaign_performance(self, customer_id: str) -> pd.DataFrame:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()

    def conversion_paths(self, customer_id: str) -> list[list[str]]:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()


class LiveMetaMarketingProvider(base.MetaMarketingProvider):
    """Stub live pentru Meta Marketing API."""

    def ad_sets(self, ad_account_id: str) -> pd.DataFrame:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _not_ready()
