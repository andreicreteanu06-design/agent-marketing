"""Sursele inteligentei SEO pentru un client: live din conturile lui, demo in rest.

Serviciul (``seo_geo_agent/services/intelligence.py``) e pur si nu stie de
token-uri. Aici se decide, pe fiecare sursa:

- **live** - clientul a conectat-o din Integrari (token + proprietate), iar
  serverul are clientul OAuth cu care token-ul se poate reimprospata;
- **demo** - sursa nu e conectata: pagina arata date demonstrative, marcate
  ca atare, ca sa se vada ce face agentul inainte de conectare;
- **unavailable** - conectata, dar inutilizabila acum (token ilizibil, server
  fara client OAuth). NU devine demo: ar arata cifre inventate ca ale clientului.

Keyword Planner e live doar cand agentul ruleaza pe conturi Google Ads reale
(``PPC_PROVIDER_MODE=live``); furnizorul mock ar pune volume inventate langa
date reale din Search Console.
"""

from __future__ import annotations

from datetime import date

import httpx
from cryptography.fernet import InvalidToken

from ppc_agent.config import ProviderMode
from ppc_agent.providers.base import KeywordPlannerProvider
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.search_data.analytics import AnalyticsDataClient
from ppc_agent.search_data.search_console import SearchConsoleClient
from ppc_agent_server.google_integrations import GoogleOAuthClient
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import ClientAccount
from ppc_agent_server.security import decrypt_secret
from ppc_agent_server.services.organic_context import ChannelSessions
from seo_geo_agent.services.intelligence import (
    AnalyticsSource,
    DailySearch,
    DailyTraffic,
    IntelligenceSources,
    PageTraffic,
    QueryStats,
    SearchSource,
    SourceKey,
    SourceStatus,
    VolumeSource,
    Window,
)
from seo_geo_agent.services.intelligence_demo import (
    DEMO_NOTES,
    DemoAnalyticsSource,
    DemoSearchSource,
    DemoVolumeSource,
    demo_brand,
)

#: Cate cuvinte trimitem la Keyword Planner - cele cu cel mai mult trafic.
_MAX_VOLUME_SEEDS = 20


class GscSearchSource:
    """Search Console, prin clientul existent din ``ppc_agent.search_data``."""

    def __init__(self, client: SearchConsoleClient) -> None:
        self._client = client

    def daily(self, window: Window) -> list[DailySearch]:
        rows = self._client.fetch_search_analytics(
            start_date=window.start, end_date=window.end, dimensions=("date",)
        )
        return [DailySearch(row.day, row.clicks, row.impressions, row.position) for row in rows]

    def queries(self, window: Window) -> list[QueryStats]:
        """Agregat pe cuvant din perechile (cuvant, pagina).

        Pagina pastrata e cea cu cele mai multe afisari pentru cuvant.
        """
        totals: dict[str, list[float]] = {}
        best_page: dict[str, tuple[int, str]] = {}
        for row in self._client.fetch_query_pages(start_date=window.start, end_date=window.end):
            clicks, impressions, weighted = totals.setdefault(row.query, [0, 0, 0.0])
            totals[row.query] = [
                clicks + row.clicks,
                impressions + row.impressions,
                weighted + row.position * row.impressions,
            ]
            if row.impressions > best_page.get(row.query, (-1, ""))[0]:
                best_page[row.query] = (row.impressions, row.page)
        return [
            QueryStats(
                query=query,
                clicks=int(clicks),
                impressions=int(impressions),
                position=weighted / impressions if impressions else 0.0,
                page=best_page[query][1],
            )
            for query, (clicks, impressions, weighted) in totals.items()
        ]


class Ga4AnalyticsSource:
    """GA4, prin ``AnalyticsDataClient``."""

    def __init__(self, client: AnalyticsDataClient) -> None:
        self._client = client

    def daily(self, window: Window) -> list[DailyTraffic]:
        return [
            DailyTraffic(row.day, row.sessions, row.pageviews, row.engaged_sessions)
            for row in self._client.daily_totals(start_date=window.start, end_date=window.end)
        ]

    def pages(self, window: Window) -> list[PageTraffic]:
        return [
            PageTraffic(row.path, row.sessions, row.engaged_sessions)
            for row in self._client.landing_pages(start_date=window.start, end_date=window.end)
        ]

    def channels(self, window: Window) -> list[ChannelSessions]:
        """Sesiunile pe canal, in ``window`` si in perioada egala de dinainte (Regina)."""
        before = window.previous
        now = self._client.channel_sessions(start_date=window.start, end_date=window.end)
        then = self._client.channel_sessions(start_date=before.start, end_date=before.end)
        return [
            ChannelSessions(channel, now.get(channel, 0), then.get(channel, 0))
            for channel in sorted(now.keys() | then.keys())
        ]


class KeywordPlannerVolumes:
    """Volumele lunare din Keyword Planner, pentru cuvintele cu trafic si ideile lor."""

    def __init__(self, provider: KeywordPlannerProvider, *, geo: str, language: str) -> None:
        self._provider = provider
        self._geo = geo
        self._language = language

    def volumes(self, seeds: list[str]) -> dict[str, int]:
        if not seeds:
            return {}
        frame = self._provider.expand(seeds[:_MAX_VOLUME_SEEDS], self._geo, self._language)
        volumes = frame.dropna(subset=["avg_monthly_searches"])
        return {
            str(keyword): int(float(volume))
            for keyword, volume in zip(
                volumes["keyword"], volumes["avg_monthly_searches"], strict=True
            )
        }


def _secret(encrypted: str) -> str | None:
    try:
        return decrypt_secret(encrypted)
    except (InvalidToken, RuntimeError):
        return None


def build_sources(
    account: ClientAccount,
    *,
    oauth: GoogleOAuthClient | None,
    transport: httpx.BaseTransport | None,
    today: date,
) -> IntelligenceSources:
    """Sursele clientului, fiecare in starea ei (live / demo / unavailable)."""
    seed = account.target_domain or f"client-{account.id}"
    brand = demo_brand(account.target_domain)
    notes: dict[SourceKey, str] = {}
    reconnect = "Conectată, dar token-ul nu se poate folosi - reconectează din Integrări."
    no_oauth = "Conectată, dar serverul nu are clientul OAuth Google configurat."

    analytics: AnalyticsSource | None
    analytics_status: SourceStatus
    if not (account.ga4_refresh_token_enc and account.ga4_property_id):
        analytics, analytics_status = DemoAnalyticsSource(seed, today), "demo"
        notes["ga4"] = DEMO_NOTES["ga4"]
    elif oauth is None or (token := _secret(account.ga4_refresh_token_enc)) is None:
        analytics, analytics_status = None, "unavailable"
        notes["ga4"] = no_oauth if oauth is None else reconnect
    else:
        analytics_status = "live"
        analytics = Ga4AnalyticsSource(
            AnalyticsDataClient(
                property_id=account.ga4_property_id,
                client_id=oauth.client_id,
                client_secret=oauth.client_secret,
                refresh_token=token,
                transport=transport,
            )
        )

    search: SearchSource | None
    search_status: SourceStatus
    if not (account.gsc_refresh_token_enc and account.gsc_site_url):
        search, search_status = DemoSearchSource(seed, today, brand), "demo"
        notes["gsc"] = DEMO_NOTES["gsc"]
    elif oauth is None or (token := _secret(account.gsc_refresh_token_enc)) is None:
        search, search_status = None, "unavailable"
        notes["gsc"] = no_oauth if oauth is None else reconnect
    else:
        search_status = "live"
        search = GscSearchSource(
            SearchConsoleClient(
                site_url=account.gsc_site_url,
                client_id=oauth.client_id,
                client_secret=oauth.client_secret,
                refresh_token=token,
                transport=transport,
            )
        )

    volumes: VolumeSource | None = None
    volumes_status: SourceStatus = "not_connected"
    if search_status == "demo":
        volumes, volumes_status = DemoVolumeSource(brand), "demo"
        notes["keyword_planner"] = DEMO_NOTES["keyword_planner"]
    elif search_status == "live":
        factory = ProviderFactory(_app_config_for(account))
        if factory.mode is ProviderMode.LIVE:
            volumes, volumes_status = (
                KeywordPlannerVolumes(
                    factory.keyword_planner(), geo=account.geo, language=account.language
                ),
                "live",
            )
        else:
            notes["keyword_planner"] = (
                "Volumele vin din Keyword Planner când agentul rulează pe conturi Google Ads "
                "reale (PPC_PROVIDER_MODE=live)."
            )

    return IntelligenceSources(
        analytics=analytics,
        analytics_status=analytics_status,
        search=search,
        search_status=search_status,
        volumes=volumes,
        volumes_status=volumes_status,
        notes=notes,
    )
