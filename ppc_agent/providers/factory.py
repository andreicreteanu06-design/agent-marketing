"""Selecteaza implementarile ``mock`` sau ``live`` in functie de configuratie."""

from __future__ import annotations

from ppc_agent.config import AppConfig, ProviderMode, Settings
from ppc_agent.providers import base, live, mock
from ppc_agent.providers.live.chatgpt_ads import LiveChatGptAdsMutations
from ppc_agent.providers.live.google_ads import LiveGoogleAdsMutations
from ppc_agent.providers.live.tiktok import LiveTikTokMutations

#: Ce trebuie sa existe in setari ca o sursa ``live`` sa poata fi citita. Fara ele,
#: providerul live ar ridica ``SetupRequiredError`` - si ar opri tot jobul de noapte,
#: desi clientul (ex. un pilot doar pe Meta) nu foloseste deloc platforma aceea.
_REQUIRED_SETTINGS: dict[str, tuple[str, ...]] = {
    "google_ads": (
        "google_ads_developer_token",
        "google_ads_refresh_token",
        "google_ads_customer_id",
    ),
    "keyword_planner": (
        "google_ads_developer_token",
        "google_ads_refresh_token",
        "google_ads_customer_id",
    ),
    "tiktok_ads": ("tiktok_access_token", "tiktok_advertiser_id"),
    "chatgpt_ads": ("chatgpt_ads_api_key",),
    "meta_ads": ("meta_access_token", "meta_ad_account_id"),
    "gsc": ("google_oauth_refresh_token",),
    "gbp": ("google_oauth_refresh_token", "gbp_location_id"),
}


class ProviderFactory:
    """Construieste furnizori concreti pornind de la :class:`AppConfig`.

    Ramura ``mock`` exista pentru toti furnizorii in afara de OpenAI Ads (ChatGPT);
    ramura ``live`` are clienti reali pentru toti.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def settings(self) -> Settings:
        """Setarile din care se construiesc furnizorii (cheile clientului incluse)."""
        return self._config.settings

    @property
    def mode(self) -> ProviderMode:
        """Modul activ al furnizorilor (``mock`` sau ``live``)."""
        return self._config.provider_mode

    def configured(self, source: str) -> bool:
        """Adevarat daca ``source`` (cheie din ``_REQUIRED_SETTINGS``) se poate citi acum.

        In ``mock`` totul e disponibil. In ``live``, o sursa fara chei/cont e sarita de
        apelant - nu inlocuita cu date mock: cifre fictive amestecate in decizii reale
        ar fi mai rau decat lipsa lor.
        """
        if self.mode is not ProviderMode.LIVE:
            # ChatGPT n-are date mock: un brat inventat ar schimba planul tuturor.
            return source != "chatgpt_ads"
        settings = self._config.settings
        return all(getattr(settings, field) for field in _REQUIRED_SETTINGS[source])

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
                access_token=self._config.settings.meta_access_token,
                currency=self._config.settings.meta_currency,  # bugetele citite, in lei
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

    def google_ads_mutations(self) -> LiveGoogleAdsMutations | None:
        """Schimbarile in contul Google Ads, sau ``None`` cand nu se poate scrie: mod
        ``mock`` sau cont neconfigurat (vezi :meth:`meta_mutations`)."""
        if self.mode is not ProviderMode.LIVE or not self.configured("google_ads"):
            return None
        reader = self.google_ads()
        assert isinstance(reader, live.LiveGoogleAdsProvider)
        return LiveGoogleAdsMutations(reader, self._config.settings.google_ads_customer_id)

    def tiktok_mutations(self) -> LiveTikTokMutations | None:
        """Schimbarile in contul TikTok, sau ``None`` (ca :meth:`google_ads_mutations`)."""
        if self.mode is not ProviderMode.LIVE or not self.configured("tiktok_ads"):
            return None
        reader = self.tiktok_ads()
        assert isinstance(reader, live.LiveTikTokAdsProvider)
        return LiveTikTokMutations(reader, self._config.settings.tiktok_advertiser_id)

    def chatgpt_ads(self) -> live.LiveChatGptAdsProvider:
        """Campaniile OpenAI Ads (ChatGPT). Doar live: nu exista o varianta mock."""
        return live.LiveChatGptAdsProvider(api_key=self._config.settings.chatgpt_ads_api_key)

    def chatgpt_mutations(self) -> LiveChatGptAdsMutations | None:
        """Schimbarile in contul OpenAI Ads, sau ``None`` (ca :meth:`google_ads_mutations`)."""
        if self.mode is not ProviderMode.LIVE or not self.configured("chatgpt_ads"):
            return None
        return LiveChatGptAdsMutations(self.chatgpt_ads())

    def tiktok_ads(self) -> base.TikTokAdsProvider:
        """Returneaza furnizorul TikTok Ads (performanta + parcursuri) pentru modul activ."""
        if self.mode is ProviderMode.LIVE:
            return live.LiveTikTokAdsProvider(
                access_token=self._config.settings.tiktok_access_token
            )
        return mock.MockTikTokAdsProvider()
