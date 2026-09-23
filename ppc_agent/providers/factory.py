"""Selecteaza implementarile ``mock`` sau ``live`` in functie de configuratie."""

from __future__ import annotations

from ppc_agent.config import AppConfig, ProviderMode
from ppc_agent.providers import base, live, mock


class ProviderFactory:
    """Construieste furnizori concreti pornind de la :class:`AppConfig`.

    Ramura ``mock`` este implementata pentru toti furnizorii: crawler, GSC, GBP,
    Keyword Planner (Modulul 1), Google Ads + TikTok Ads (Modulul 2) si Meta
    Marketing (Modulul 3). Ramura ``live`` este momentan formata din stub-uri care
    ridica :class:`ppc_agent.errors.SetupRequiredError`.
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
            settings = self._config.settings
            return live.LiveGscProvider(
                site_url=settings.gsc_site_url,
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                refresh_token=settings.google_oauth_refresh_token,
            )
        return mock.MockGscProvider()

    def gbp(self) -> base.GbpProvider:
        """Returneaza furnizorul Google Business Profile pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            settings = self._config.settings
            return live.LiveGbpProvider(
                account_id=settings.gbp_account_id,
                location_id=settings.gbp_location_id,
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                refresh_token=settings.google_oauth_refresh_token,
            )
        return mock.MockGbpProvider()

    def keyword_planner(self) -> base.KeywordPlannerProvider:
        """Returneaza furnizorul Keyword Planner pentru modul activ.

        Foloseste credentialele Google ADS, nu cele de Search Console/Business
        Profile: Keyword Planner e parte din Google Ads API, cu alt scope
        ('adwords') si alt token de dezvoltator.
        """
        if self.mode is ProviderMode.LIVE:
            settings = self._config.settings
            return live.LiveKeywordPlannerProvider(
                developer_token=settings.google_ads_developer_token,
                client_id=settings.google_ads_client_id,
                client_secret=settings.google_ads_client_secret,
                refresh_token=settings.google_ads_refresh_token,
                customer_id=settings.google_ads_customer_id,
                login_customer_id=settings.google_ads_login_customer_id,
            )
        return mock.MockKeywordPlannerProvider()

    def google_ads(self) -> base.GoogleAdsProvider:
        """Returneaza furnizorul Google Ads (performanta + parcursuri) pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            settings = self._config.settings
            return live.LiveGoogleAdsProvider(
                developer_token=settings.google_ads_developer_token,
                client_id=settings.google_ads_client_id,
                client_secret=settings.google_ads_client_secret,
                refresh_token=settings.google_ads_refresh_token,
                login_customer_id=settings.google_ads_login_customer_id,
            )
        return mock.MockGoogleAdsProvider()

    def meta(self) -> base.MetaMarketingProvider:
        """Returneaza furnizorul Meta Marketing pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveMetaMarketingProvider(
                access_token=self._config.settings.meta_access_token
            )
        return mock.MockMetaMarketingProvider()

    def meta_mutations(self) -> live.LiveMetaMarketingProvider | None:
        """Providerul Meta capabil de SCRIERE, sau ``None`` cand nu se poate scrie.

        Separat de :meth:`meta` fiindca tipul returnat e altul: ``meta()``
        promite contractul de citire (``MetaMarketingProvider``), pe care
        varianta ``mock`` il implementeaza la fel de bine; mutatiile exista
        doar pe clientul live.

        ``None`` in doua cazuri, amandoua intentionate:

        - **mod ``mock``**: nu intoarcem un dublu care "reuseste". O propunere
          marcata executata fara ca nimic sa se fi schimbat intr-un cont real e
          exact minciuna pe care toata poarta HITL exista ca sa o previna.
        - **fara token**: clientul nu si-a conectat contul Meta.

        Apelantul traduce ``None`` intr-un raspuns care spune omului ce sa faca
        (vezi ``routers/proposals.py``).
        """
        if self.mode is not ProviderMode.LIVE:
            return None
        settings = self._config.settings
        if not settings.meta_access_token:
            return None
        return live.LiveMetaMarketingProvider(
            access_token=settings.meta_access_token,
            currency=settings.meta_currency,
        )

    def tiktok_ads(self) -> base.TikTokAdsProvider:
        """Returneaza furnizorul TikTok Ads (performanta + parcursuri) pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveTikTokAdsProvider(
                access_token=self._config.settings.tiktok_access_token
            )
        return mock.MockTikTokAdsProvider()
