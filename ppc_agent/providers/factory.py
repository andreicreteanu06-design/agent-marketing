"""Selecteaza implementarile ``mock`` sau ``live`` in functie de configuratie."""

from __future__ import annotations

from typing import NoReturn

from ppc_agent.config import AppConfig, ProviderMode
from ppc_agent.providers import base, live


class ProviderFactory:
    """Construieste furnizori concreti pornind de la :class:`AppConfig`.

    In Faza 0 doar ramura ``live`` este cablata (stub-uri care ridica
    :class:`ppc_agent.errors.SetupRequiredError`). Implementarile ``mock``
    concrete se adauga in Modulul 1 (crawler, GSC, GBP, Keyword Planner) si
    Modulul 3 (Meta).
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
        return self._mock_pending("crawler")

    def gsc(self) -> base.GscProvider:
        """Returneaza furnizorul Google Search Console pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveGscProvider()
        return self._mock_pending("gsc")

    def gbp(self) -> base.GbpProvider:
        """Returneaza furnizorul Google Business Profile pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveGbpProvider()
        return self._mock_pending("gbp")

    def keyword_planner(self) -> base.KeywordPlannerProvider:
        """Returneaza furnizorul Keyword Planner pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveKeywordPlannerProvider()
        return self._mock_pending("keyword_planner")

    def meta(self) -> base.MetaMarketingProvider:
        """Returneaza furnizorul Meta Marketing pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveMetaMarketingProvider()
        return self._mock_pending("meta")

    @staticmethod
    def _mock_pending(name: str) -> NoReturn:
        """Semnaleaza ca furnizorul ``mock`` cerut nu este inca implementat."""
        raise NotImplementedError(
            f"Furnizorul mock '{name}' se adauga intr-o faza urmatoare."
        )
