"""Selecteaza implementarile ``mock`` sau ``live`` in functie de configuratie."""

from __future__ import annotations

from ppc_agent.config import AppConfig, ProviderMode
from ppc_agent.providers import base, live, mock


class ProviderFactory:
    """Construieste furnizori concreti pornind de la :class:`AppConfig`.

    Ramura ``mock`` este implementata pentru crawler, GSC, GBP si Keyword Planner
    (Modulul 1) si Google Ads (Modulul 2); furnizorul Meta se adauga in Modulul 3.
    Ramura ``live`` este momentan formata din stub-uri care ridica
    :class:`ppc_agent.errors.SetupRequiredError`.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def mode(self) -> ProviderMode:
        """Modul activ al furnizorilor (``mock`` sau ``live``)."""
        return self._config.provider_mode

    def crawler(self) -> base.CrawlerProvider:
        """Returneaza furnizorul de crawling pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveCrawlerProvider()
        return mock.MockCrawlerProvider()

    def gsc(self) -> base.GscProvider:
        """Returneaza furnizorul Google Search Console pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveGscProvider()
        return mock.MockGscProvider()

    def gbp(self) -> base.GbpProvider:
        """Returneaza furnizorul Google Business Profile pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveGbpProvider()
        return mock.MockGbpProvider()

    def keyword_planner(self) -> base.KeywordPlannerProvider:
        """Returneaza furnizorul Keyword Planner pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveKeywordPlannerProvider()
        return mock.MockKeywordPlannerProvider()

    def google_ads(self) -> base.GoogleAdsProvider:
        """Returneaza furnizorul Google Ads (performanta + parcursuri) pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveGoogleAdsProvider()
        return mock.MockGoogleAdsProvider()

    def meta(self) -> base.MetaMarketingProvider:
        """Returneaza furnizorul Meta Marketing pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveMetaMarketingProvider()
        raise NotImplementedError(
            "Furnizorul mock Meta Marketing se adauga in Modulul 3."
        )
