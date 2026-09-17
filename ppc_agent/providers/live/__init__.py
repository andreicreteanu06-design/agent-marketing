"""Furnizorii ``live``.

Google/Meta/TikTok Ads (performanta pentru bandit + lichiditate Meta) au
implementari reale — vezi ``google_ads.py``/``meta.py``/``tiktok.py``, acelasi
pattern ca :class:`ppc_agent.copywriter.llm.LiveLLMClient` (httpx simplu,
testabil cu ``httpx.MockTransport``). Restul (crawler, Google Search Console,
Google Business Profile, Keyword Planner — Modulul 1; Generative Engine Ads —
vezi mai jos) raman stub-uri: fiecare metoda ridica
:class:`ppc_agent.errors.SetupRequiredError`, niciun apel de retea nu este
efectuat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers import base
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider

if TYPE_CHECKING:
    from decimal import Decimal

    import pandas as pd

__all__ = [
    "LiveCrawlerProvider",
    "LiveGbpProvider",
    "LiveGenerativeEngineProvider",
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


# Verificat manual (cercetare septembrie 2026, vezi rezumatul conversatiei) -
# NU presupuneri: OpenAI Ads API e reala (developers.openai.com/ads;
# api.ads.openai.com/v1, Bearer <OPENAI_ADS_API_KEY>, Campaigns/Ad Groups/
# Campaign Targeting), dar accesul e limitat la parteneri aprobati (fara acces
# public general la data cercetarii). Perplexity a ABANDONAT reclamele in
# februarie 2026 (subscription-only, fara API de integrat) - nu exista niciun
# stub separat pentru Perplexity aici, ca sa nu sugereze o integrare posibila
# azi care pur si simplu nu exista.
_GENERATIVE_ENGINE_HINT = (
    "Generative Engine Ads (ChatGPT) nu e inca implementat. OpenAI Ads API e "
    "reala (developers.openai.com/ads), dar accesul de azi e limitat la "
    "parteneri aprobati - cere un OPENAI_ADS_API_KEY via ads.openai.com si "
    "implementeaza clientul in acest fisier cand contul e aprobat."
)


def _generative_engine_not_ready() -> NoReturn:
    """Ridica intotdeauna :class:`SetupRequiredError` cu detalii specifice OpenAI Ads."""
    raise SetupRequiredError(_GENERATIVE_ENGINE_HINT)


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


class LiveGenerativeEngineProvider(base.BaseMarketingProvider):
    """Stub live pentru reclame in ChatGPT (OpenAI Ads).

    OpenAI Ads e real (self-serve din mai 2026, campanii cu buget minim 25
    USD/zi, targetare contextuala pe conversatie, NU pe cuvinte cheie ca
    Google) — vezi https://developers.openai.com/ads. API-ul programatic
    (``api.ads.openai.com/v1/campaigns``, obiecte ``Campaign``/``AdGroup``)
    exista si el, dar accesul e limitat la parteneri aprobati de OpenAI (nu
    exista inca un cont de agentie aprobat pentru acest proiect) - de-asta
    ramane stub, ca celelalte 4 furnizori live neconectati inca, nu pentru ca
    "citation placement API" (cum descria cererea initiala) ar fi o formulare
    corecta - numele real e pur si simplu "OpenAI Ads API".

    Cand un cont e aprobat: implementeaza ``get_campaign_metrics`` peste
    ``GET /campaigns``, ``scale_budget`` peste
    ``POST /campaigns/{id}`` (campul real e ``budget.lifetime_spend_limit_micros``
    - buget PE VIATA campaniei, nu zilnic ca Google/Meta/TikTok, deci
    ``scale_budget`` va trebui sa recalculeze plafonul in functie de zilele
    ramase), ``pause_ad`` peste ``POST /campaigns/{id}/pause``.
    """

    def get_campaign_metrics(self, account_id: str) -> pd.DataFrame:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _generative_engine_not_ready()

    def scale_budget(self, campaign_id: str, new_daily_budget: Decimal) -> None:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _generative_engine_not_ready()

    def pause_ad(self, ad_id: str) -> None:
        """Nu este disponibil inca — vezi :class:`SetupRequiredError`."""
        _generative_engine_not_ready()
