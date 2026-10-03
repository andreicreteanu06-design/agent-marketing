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
- ``gbp.py`` — Business Information + recenzii (acces aprobat de Google);
- ``chatgpt_ads.py`` — campaniile OpenAI Ads (ChatGPT), cu bugetul si pauza lor.
"""

from __future__ import annotations

from ppc_agent.providers.live.chatgpt_ads import LiveChatGptAdsProvider
from ppc_agent.providers.live.crawler import LiveCrawlerProvider
from ppc_agent.providers.live.gbp import LiveGbpProvider
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.keyword_planner import LiveKeywordPlannerProvider
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from ppc_agent.providers.live.search_console import LiveGscProvider
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider

__all__ = [
    "LiveChatGptAdsProvider",
    "LiveCrawlerProvider",
    "LiveGbpProvider",
    "LiveGoogleAdsProvider",
    "LiveGscProvider",
    "LiveKeywordPlannerProvider",
    "LiveMetaMarketingProvider",
    "LiveTikTokAdsProvider",
]
