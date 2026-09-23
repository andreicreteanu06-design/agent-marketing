"""Furnizorii ``live``.

Toti furnizorii Modulelor 1-3 au acum implementari reale, in module proprii,
dupa acelasi pattern (``httpx`` simplu, ``transport`` injectabil, testabil cu
``httpx.MockTransport``, fara SDK-uri oficiale):

- ``google_ads.py``/``meta.py``/``tiktok.py`` — performanta pentru bandit,
  lichiditate Meta, plus mutatiile Meta;
- ``crawler.py`` — peste motorul de audit din ``seo_geo_agent``, ca sa nu
  existe doua crawlere cu doua politici de siguranta in acelasi repo;
- ``search_console.py`` — peste ``search_data.SearchConsoleClient``;
- ``keyword_planner.py`` — ``GenerateKeywordIdeas`` din Google Ads API;
- ``gbp.py`` — Business Information + recenzii (acces aprobat de Google).

Singurul stub ramas e :class:`LiveGenerativeEngineProvider` (OpenAI Ads) — vezi
mai jos de ce.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers import base
from ppc_agent.providers.live.crawler import LiveCrawlerProvider
from ppc_agent.providers.live.gbp import LiveGbpProvider
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.keyword_planner import LiveKeywordPlannerProvider
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.live.search_console import LiveGscProvider
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
