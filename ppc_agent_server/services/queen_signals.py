"""Semnalele Reginei pentru un client real: baza de date + Search Console.

Singurul loc care stie de unde vin datele Reginei - ``queen_agent.py`` ramane
pur si le primeste gata adunate (:class:`~ppc_agent_server.services.queen_agent.BrandSignals`):

- **cautarile organice** vin de la agentul SEO/GEO (``seo_intelligence``), dar
  DOAR cand Search Console e conectat (``live``). Datele demonstrative ale
  paginii "Trafic & Pozitii" (un service auto inventat) nu au voie sa ajunga
  intr-o directiva pentru un client real;
- **traficul** (pentru Regina, ``organic_context.py``): sesiunile pe canal din GA4
  (Meta fata de Google organic), click-urile si pozitia medie din Search Console -
  tot doar ``live`` - si pozitiile urmarite in SERP (``SerpPosition``);
- **termenii platiti** (cu conversii) vin din ``SearchTermConversion``;
- **reclamele live** sunt cele pe care agentul le-a pus in cont si inca
  ruleaza: campaniile Meta lansate prin aprobare (textul e in propunerea
  executata, iar ``ad_id``-ul creat leaga textul de ``AdPerformanceRecord``)
  si copy-urile aprobate din coada (``AdQueueItem``), fara performanta legata;
- **banii** (pentru CFO-ul din consiliul de chat, ``council.py``) vin din
  ``AdPerformanceRecord`` (Meta/TikTok, de la lansare), termenii Google Ads pe
  fereastra, plafonul zilnic al contului si propunerile in asteptare;
- **datele tehnice** (pentru Tehnician, ``technician.py``): conversiile zi de zi
  - Google Ads din ``SearchTermConversion`` (cu click-urile zilei), comenzile si
  apelurile din ``ConversionEvent`` (pe sursa webhook-ului) -, ultima
  masuratoare PageSpeed pe mobil (``SiteSpeedSample``, cu datele CrUX) si ultimul
  audit tehnic SEO/GEO al site-ului (``SiteAuditSnapshot``);
- **memoria consiliului** (``memory.py``): ``MemoryStream`` + propunerile
  respinse sau esuate din ``ProposedChange``, ca istoric;
- **piata** (pentru Researcher, ``researcher.py``): cererea din Google Trends
  (``market_trends.py``) si cautarea pe web, amandoua reale, pe nisa si orasul scoase
  din cautarile clientului. Licitatia si durerile din recenzii nu au inca o sursa:
  raman necunoscute.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, Protocol

import httpx
from sqlmodel import Session, col, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.errors import PpcAgentError
from ppc_agent_server.hybrid_queries import DEFAULT_WINDOW_DAYS, load_paid_terms, window_start
from ppc_agent_server.models import (
    AdPerformanceRecord,
    AdQueueItem,
    AdQueueStatus,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ConversionEvent,
    MemoryStream,
    PlatformArmSnapshot,
    ProposedChange,
    SearchTermConversion,
    SerpPosition,
    SerpSource,
    SiteAuditSnapshot,
    SiteSpeedSample,
    TrackingEvidence,
)
from ppc_agent_server.services.council import AdSpend, FinancialSignals, TermSpend
from ppc_agent_server.services.market_trends import (
    TrendsSource,
    google_trends,
    load_trend_demand,
)
from ppc_agent_server.services.memory import (
    DEDUPE_DAYS,
    FAILED_LOOKBACK_DAYS,
    HISTORY_LIMIT,
    AgentRole,
    MemoryEntry,
    compress,
)
from ppc_agent_server.services.organic_context import (
    ChannelSessions,
    KeywordRank,
    OrganicSearchTotals,
    OrganicSignals,
)
from ppc_agent_server.services.queen_agent import BrandSignals, LiveAd, SearchSignal
from ppc_agent_server.services.researcher import (
    DemandSeries,
    MarketSignals,
    RelevanceVerifier,
    WebStatus,
    market_focus,
    search_market_web,
)
from ppc_agent_server.services.technician import (
    AuditIssue,
    AuditSeverity,
    DailyConversions,
    MobileSpeed,
    SiteAudit,
    SyntheticEvidence,
    TechnicalSignals,
    TrackingStream,
)
from ppc_agent_server.skills import SkillRegistry, skill_registry
from ppc_agent_server.skills.web_search import WebFinding
from ppc_agent_server.tracking.pipeline import shop_revenue
from seo_geo_agent.audit.geo_reporters import brand_token_from_url
from seo_geo_agent.services.intelligence import DailySearch, Window

logger = logging.getLogger("ppc_agent_server.services.queen_signals")

#: Fereastra de cautari organice - aceeasi ca implicita paginii "Trafic & Pozitii".
ORGANIC_WINDOW_DAYS = 28
#: Cat asteapta Researcher-ul Google Trends (trei cereri: cookie, token, seria).
TRENDS_WAIT_SECONDS = 20.0
#: Perioada comparata de Researcher (licitatie, mentiuni) - aceeasi ca traficul.
MARKET_PERIOD_DAYS = 28
#: Firele pentru Google Trends (cereri blocante, cu termenele lor in ``market_trends``).
_TRENDS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="google-trends")


def _utc_today() -> date:
    return datetime.now(tz=UTC).date()


class SeoIntentSource(Protocol):
    """Cautarile organice ale unui client, plus notele despre ce lipseste."""

    def queries(self, account: ClientAccount) -> tuple[list[SearchSignal], list[str]]: ...


class SearchConsoleIntent:
    """Cautarile din Search Console, prin sursele agentului SEO/GEO. Doar ``live``."""

    def __init__(
        self,
        *,
        today: Callable[[], date] = date.today,
        transport: httpx.BaseTransport | None = None,
        days: int = ORGANIC_WINDOW_DAYS,
    ) -> None:
        self._today = today
        self._transport = transport
        self._days = days

    def queries(self, account: ClientAccount) -> tuple[list[SearchSignal], list[str]]:
        # Importuri tarzii: ``seo_intelligence`` importa ``jobs.tasks``, care
        # importa (prin ``jobs.brand_alignment``) acest modul - la nivel de modul
        # ar fi un import circular.
        from ppc_agent_server.google_integrations import google_oauth_client
        from ppc_agent_server.routers.seo_intelligence import DATA_LAG_DAYS
        from ppc_agent_server.seo_intelligence import build_sources

        today = self._today()
        sources = build_sources(
            account, oauth=google_oauth_client(), transport=self._transport, today=today
        )
        if sources.search_status != "live" or sources.search is None:
            return [], [
                "Search Console nu e conectat (sau nu se poate folosi acum): Regina a lucrat "
                "doar cu termenii plătiți - nu folosește datele demonstrative."
            ]
        window = Window.ending(today - timedelta(days=DATA_LAG_DAYS), self._days)
        try:
            stats = sources.search.queries(window)
        except (PpcAgentError, httpx.HTTPError) as exc:
            return [], [
                f"Search Console nu a răspuns ({type(exc).__name__}): Regina a lucrat doar "
                "cu termenii plătiți."
            ]
        return [
            SearchSignal(
                query=stat.query,
                origin="organic",
                impressions=stat.impressions,
                clicks=stat.clicks,
            )
            for stat in stats
        ], []


class OrganicTrafficSource(Protocol):
    """Traficul unui client din conturile Google conectate (GA4, Search Console)."""

    def load(self, account: ClientAccount) -> OrganicSignals: ...


def _search_totals(
    now: Sequence[DailySearch], before: Sequence[DailySearch]
) -> OrganicSearchTotals:
    def _position(rows: Sequence[DailySearch]) -> float | None:
        impressions = sum(row.impressions for row in rows)
        if not impressions:
            return None
        return round(sum(row.position * row.impressions for row in rows) / impressions, 1)

    return OrganicSearchTotals(
        clicks_now=sum(row.clicks for row in now),
        clicks_before=sum(row.clicks for row in before),
        impressions_now=sum(row.impressions for row in now),
        impressions_before=sum(row.impressions for row in before),
        position_now=_position(now),
        position_before=_position(before),
    )


class GoogleOrganicTraffic:
    """GA4 (sesiunile pe canal) si Search Console (click-uri, pozitia medie). Doar ``live``.

    Un cont neconectat nu primeste date demonstrative: nota spune ce lipseste.
    """

    def __init__(
        self,
        *,
        today: Callable[[], date] = date.today,
        transport: httpx.BaseTransport | None = None,
        days: int = ORGANIC_WINDOW_DAYS,
    ) -> None:
        self._today = today
        self._transport = transport
        self._days = days

    def load(self, account: ClientAccount) -> OrganicSignals:
        # Importuri tarzii, ca la ``SearchConsoleIntent``: altfel import circular.
        from ppc_agent_server.google_integrations import google_oauth_client
        from ppc_agent_server.routers.seo_intelligence import DATA_LAG_DAYS
        from ppc_agent_server.seo_intelligence import Ga4AnalyticsSource, build_sources

        today = self._today()
        sources = build_sources(
            account, oauth=google_oauth_client(), transport=self._transport, today=today
        )
        window = Window.ending(today - timedelta(days=DATA_LAG_DAYS), self._days)
        notes: list[str] = []
        channels: list[ChannelSessions] = []
        if sources.analytics_status == "live" and isinstance(
            sources.analytics, Ga4AnalyticsSource
        ):
            try:
                channels = sources.analytics.channels(window)
            except (PpcAgentError, httpx.HTTPError) as exc:
                notes.append(
                    f"GA4 nu a răspuns ({type(exc).__name__}): traficul pe canale lipsește."
                )
        else:
            notes.append(
                "GA4 nu e conectat: nu pot compara traficul din Meta cu cel din Google organic."
            )
        search: OrganicSearchTotals | None = None
        if sources.search_status == "live" and sources.search is not None:
            try:
                search = _search_totals(
                    sources.search.daily(window), sources.search.daily(window.previous)
                )
            except (PpcAgentError, httpx.HTTPError) as exc:
                notes.append(
                    f"Search Console nu a răspuns ({type(exc).__name__}): lipsesc click-urile "
                    "organice."
                )
        return OrganicSignals(
            window_days=self._days, channels=channels, search=search, notes=notes
        )


def _bare_domain(value: str) -> str:
    host = value.strip().lower()
    host = host.split("://", 1)[-1].split("/", 1)[0]
    return host.removeprefix("www.")


def load_keyword_ranks(
    session: Session, account: ClientAccount, *, today: date, days: int = ORGANIC_WINDOW_DAYS
) -> list[KeywordRank]:
    """Pozitiile urmarite ale site-ului (OpenSERP): ultima verificare din fiecare perioada.

    Doar cuvintele verificate in AMBELE perioade; un rand cu ``rank=None`` inseamna
    "verificat, nu apare" si se pastreaza ca atare.
    """
    domain = _bare_domain(account.target_domain)
    if not domain:
        return []
    start = datetime.combine(today - timedelta(days=days), time.min, tzinfo=UTC)
    since = start - timedelta(days=days)
    rows = session.exec(
        select(SerpPosition)
        .where(SerpPosition.client_account_id == account.id)
        .where(SerpPosition.source == SerpSource.OPENSERP)
        .where(SerpPosition.checked_on >= since)
        .order_by(SerpPosition.checked_on)  # type: ignore[arg-type]
    ).all()
    before: dict[str, float | None] = {}
    now: dict[str, float | None] = {}
    for row in rows:
        if _bare_domain(row.domain) != domain:
            continue  # pozitiile concurentilor
        # Ordonate crescator: ultima verificare din fiecare perioada ramane.
        target = now if _utc(row.checked_on) >= start else before
        target[row.keyword] = row.rank
    return [
        KeywordRank(keyword=keyword, rank_before=before[keyword], rank_now=now[keyword])
        for keyword in sorted(before.keys() & now.keys())
    ]


@dataclass(slots=True)
class _PaidTotals:
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0


def load_paid_signals(
    session: Session, client_account_id: int, *, days: int = DEFAULT_WINDOW_DAYS
) -> list[SearchSignal]:
    """Termenii de cautare platiti, agregati pe termen peste fereastra."""
    rows = session.exec(
        select(SearchTermConversion)
        .where(SearchTermConversion.client_account_id == client_account_id)
        .where(SearchTermConversion.day >= window_start(days))
    ).all()
    totals: dict[str, _PaidTotals] = {}
    for row in rows:
        bucket = totals.setdefault(row.search_term, _PaidTotals())
        bucket.impressions += row.impressions
        bucket.clicks += row.clicks
        bucket.conversions += row.conversions
    return [
        SearchSignal(
            query=term,
            origin="paid",
            impressions=data.impressions,
            clicks=data.clicks,
            conversions=data.conversions,
        )
        for term, data in sorted(totals.items())
    ]


def _paused_refs(session: Session, client_account_id: int) -> set[str]:
    """Resursele puse deja pe pauza prin aprobare - nu mai ruleaza."""
    rows = session.exec(
        select(ProposedChange.resource)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.op == ChangeOp.PAUSE)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
    ).all()
    return {str(resource) for resource in rows}


def _queue_copy_text(ad_copy: dict[str, Any]) -> tuple[str, str]:
    """Titlul si corpul unui copy din coada (Google: 2 titluri + descriere; TikTok: script)."""
    if "headline_1" in ad_copy:
        headline = " | ".join(
            str(ad_copy[key]) for key in ("headline_1", "headline_2") if ad_copy.get(key)
        )
        return headline, str(ad_copy.get("description", ""))
    headline = str(ad_copy.get("audio_hook") or ad_copy.get("visual_hook_concept") or "")
    parts: list[str] = []
    for key in ("body_script", "text_overlay", "call_to_action"):
        value = ad_copy.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return headline, " ".join(parts)


def load_live_ads(session: Session, client_account_id: int) -> list[LiveAd]:
    """Reclamele care ruleaza acum, cu textul lor si - unde se poate - performanta."""
    performance = {
        record.ad_id: record
        for record in session.exec(
            select(AdPerformanceRecord).where(
                AdPerformanceRecord.client_account_id == client_account_id
            )
        ).all()
    }
    paused = _paused_refs(session, client_account_id)
    ads: list[LiveAd] = []

    launches = session.exec(
        select(ProposedChange)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.op == ChangeOp.CREATE_CAMPAIGN)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
        .order_by(ProposedChange.id)  # type: ignore[arg-type]
    ).all()
    for launch in launches:
        ad_id = str((launch.execution_result or {}).get("ad_id", "")).strip()
        ref = f"meta_ad/{ad_id}"
        if not ad_id or ref in paused or f"ad/{ad_id}" in paused:
            continue
        record = performance.get(ad_id)
        ads.append(
            LiveAd(
                ref=ref,
                platform="meta",
                headline=str(launch.after.get("headline", "")),
                body=str(launch.after.get("primary_text", "")),
                spend=record.spend if record else None,
                conversions=record.counted[0] if record else None,
                target_cpa=record.target_cpa if record else None,
            )
        )

    approved = session.exec(
        select(AdQueueItem)
        .where(AdQueueItem.client_account_id == client_account_id)
        .where(AdQueueItem.status == AdQueueStatus.APPROVED)
        .order_by(AdQueueItem.id)  # type: ignore[arg-type]
    ).all()
    for item in approved:
        headline, body = _queue_copy_text(item.ad_copy)
        ads.append(
            LiveAd(
                ref=f"ad_queue_item/{item.id}",
                platform=item.platform.value,
                headline=headline,
                body=body,
            )
        )
    return ads


def _brand(account: ClientAccount) -> str:
    if account.brand_name:
        return account.brand_name
    domain = account.target_domain
    return brand_token_from_url(domain if "://" in domain else f"https://{domain}") or ""


class DbBrandSignals:
    """:class:`~ppc_agent_server.services.queen_agent.BrandSignalsSource` peste DB-ul serverului."""

    def __init__(
        self,
        session: Session,
        *,
        seo_intent: SeoIntentSource | None = None,
        traffic: OrganicTrafficSource | None = None,
        days: int = DEFAULT_WINDOW_DAYS,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._session = session
        self._seo_intent = seo_intent or SearchConsoleIntent()
        self._traffic = traffic or GoogleOrganicTraffic()
        self._days = days
        self._today = today

    def load(self, client_account_id: int) -> BrandSignals:
        account = self._session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        organic, notes = self._seo_intent.queries(account)
        paid = load_paid_signals(self._session, client_account_id, days=self._days)
        if not paid:
            notes.append(
                f"Niciun termen de căutare plătit în ultimele {self._days} de zile: "
                "lipsesc semnalele despre cine chiar cumpără."
            )
        return BrandSignals(
            brand=_brand(account),
            searches=[*organic, *paid],
            ads=load_live_ads(self._session, client_account_id),
            notes=notes,
            organic=self._organic(account),
        )

    def _organic(self, account: ClientAccount) -> OrganicSignals:
        """Traficul (GA4, Search Console) si pozitiile urmarite; un cont care pica nu opreste."""
        try:
            traffic = self._traffic.load(account)
        except Exception as exc:  # traficul e context pentru Regina, nu o conditie
            logger.warning("[Regina] traficul organic pentru %s: %r", account.id, exc)
            traffic = OrganicSignals(
                window_days=ORGANIC_WINDOW_DAYS,
                notes=[f"Traficul din Google nu s-a putut citi ({type(exc).__name__})."],
            )
        keywords = load_keyword_ranks(
            self._session, account, today=self._today(), days=traffic.window_days
        )
        return replace(traffic, keywords=keywords)


def _launched_headlines(session: Session, client_account_id: int) -> dict[str, str]:
    """``ad_id`` -> titlul cu care a fost lansat, din campaniile Meta aprobate."""
    launches = session.exec(
        select(ProposedChange)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.op == ChangeOp.CREATE_CAMPAIGN)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
    ).all()
    headlines: dict[str, str] = {}
    for launch in launches:
        ad_id = str((launch.execution_result or {}).get("ad_id", "")).strip()
        headline = str(launch.after.get("headline", "")).strip()
        if ad_id and headline:
            headlines[ad_id] = headline
    return headlines


class DbFinancialSignals:
    """:class:`~ppc_agent_server.services.council.FinancialSignalsSource` peste DB-ul serverului."""

    def __init__(self, session: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> None:
        self._session = session
        self._days = days

    def load(self, client_account_id: int) -> FinancialSignals:
        account = self._session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        headlines = _launched_headlines(self._session, client_account_id)
        terms = load_paid_terms(self._session, client_account_id, days=self._days)
        # Ce a citit agentul PPC din platforme azi-noapte - aceleasi cifre din care Kelly
        # si Thompson muta bugetele. Doar fara ele, rollup-ul din conversiile primite
        # prin webhook (care fara un magazin conectat nu exista deloc). Campaniile Google
        # intra doar fara termenii de cautare: aceiasi bani, numarati o singura data.
        arms = self._session.exec(
            select(PlatformArmSnapshot).where(
                PlatformArmSnapshot.client_account_id == client_account_id
            )
        ).all()
        # Tinta CPA: valoarea unei conversii / pragul de rentabilitate - la un magazin cu
        # destule vanzari, din cosul mediu real al aceleiasi ferestre.
        target = account.target_cpa(
            revenue=sum((arm.revenue for arm in arms), Decimal("0")),
            conversions=sum(arm.conversions for arm in arms),
        )
        ads = [
            AdSpend(
                ad_id=arm.arm_id,
                platform=arm.platform,
                label=arm.name,
                spend=arm.cost,
                conversions=arm.conversions,
                revenue=arm.revenue,
                target_cpa=target,
            )
            for arm in arms
            if arm.platform != "google_ads" or not terms
        ]
        records = (
            []
            if ads
            else self._session.exec(
                select(AdPerformanceRecord).where(
                    AdPerformanceRecord.client_account_id == client_account_id
                )
            ).all()
        )
        ads += [
            AdSpend(
                ad_id=record.ad_id,
                platform=record.platform.value,
                label=headlines.get(record.ad_id, ""),
                spend=record.spend,
                conversions=record.counted[0],
                revenue=record.counted[1],
                target_cpa=record.target_cpa,
            )
            for record in records
        ]
        pending = self._session.exec(
            select(ProposedChange.id)
            .where(ProposedChange.client_account_id == client_account_id)
            .where(ProposedChange.status == ChangeStatus.PENDING)
        ).all()
        notes: list[str] = []
        if not ads and not terms:
            notes.append(
                "Nicio cheltuială înregistrată: nici reclame Meta/TikTok cu performanță, nici "
                f"termeni Google Ads în ultimele {self._days} de zile."
            )
        return FinancialSignals(
            objective=account.objective.value,
            ads=ads,
            search_terms=[
                TermSpend(
                    term=term.term,
                    clicks=term.clicks,
                    cost=term.cost,
                    conversions=term.conversions,
                    value=term.conversions_value,
                )
                for term in sorted(terms, key=lambda item: item.term)
            ],
            daily_spend_cap=account.max_daily_spend,
            pending_proposals=len(pending),
            window_days=self._days,
            notes=notes,
            break_even_roas=account.break_even_roas,
            shop_revenue=shop_revenue(self._session, account, days=self._days),
            break_even_is_default=(
                account.min_roas is None and account.objective is CampaignObjective.SALES
            ),
        )


class DbTechnicalSignals:
    """:class:`~ppc_agent_server.services.technician.TechnicalSignalsSource` peste DB.

    Fereastra: ultimele ``days`` zile COMPLETE, fiecare zi prezenta (si cele fara
    niciun rand, cu zero) - o oprire se vede tocmai in zilele fara date.
    """

    def __init__(
        self,
        session: Session,
        *,
        today: Callable[[], date] = _utc_today,
        days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        self._session = session
        self._today = today
        self._days = days

    def load(self, client_account_id: int) -> TechnicalSignals:
        account = self._session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        today = self._today()
        first = today - timedelta(days=self._days)
        grid = [first + timedelta(days=offset) for offset in range(self._days)]
        since = datetime.combine(first, time.min, tzinfo=UTC)

        streams: list[TrackingStream] = []
        google = self._session.exec(
            select(SearchTermConversion)
            .where(SearchTermConversion.client_account_id == client_account_id)
            .where(SearchTermConversion.day >= since)
        ).all()
        if google or account.google_ads_customer_id:
            clicks: Counter[date] = Counter()
            conversions: defaultdict[date, float] = defaultdict(float)
            for row in google:
                clicks[row.day.date()] += row.clicks
                conversions[row.day.date()] += row.conversions
            streams.append(
                TrackingStream(
                    key="google_ads",
                    days=[
                        DailyConversions(day, round(conversions[day], 2), clicks[day])
                        for day in grid
                    ],
                )
            )

        # Toate sursele care au trimis vreodata ceva, nu doar cele din fereastra:
        # o sursa tacuta de o luna e exact ce trebuie vazut.
        sources = self._session.exec(
            select(ConversionEvent.source_platform)
            .where(ConversionEvent.client_account_id == client_account_id)
            .distinct()
        ).all()
        events = self._session.exec(
            select(ConversionEvent.source_platform, ConversionEvent.created_at)
            .where(ConversionEvent.client_account_id == client_account_id)
            .where(ConversionEvent.created_at >= since)
        ).all()
        per_source: defaultdict[str, Counter[date]] = defaultdict(Counter)
        for source, created_at in events:
            per_source[source][created_at.date()] += 1
        for source in sorted(sources):
            counts = per_source[source]
            streams.append(
                TrackingStream(
                    key=source,
                    days=[DailyConversions(day, float(counts[day])) for day in grid],
                )
            )

        # Ultimele doua masuratori: veto-ul pe LCP cere doua critice la rand.
        samples = self._session.exec(
            select(SiteSpeedSample)
            .where(SiteSpeedSample.client_account_id == client_account_id)
            .order_by(SiteSpeedSample.measured_at.desc())  # type: ignore[attr-defined]
            .limit(2)
        ).all()
        speeds = [_mobile_speed(sample) for sample in samples]
        audit = self._session.exec(
            select(SiteAuditSnapshot)
            .where(SiteAuditSnapshot.client_account_id == client_account_id)
            .order_by(SiteAuditSnapshot.audited_at.desc())  # type: ignore[attr-defined]
        ).first()
        latest = self._session.exec(
            select(TrackingEvidence)
            .where(TrackingEvidence.client_account_id == client_account_id)
            .order_by(TrackingEvidence.started_at.desc())  # type: ignore[attr-defined]
        ).first()
        notes: list[str] = []
        if account.meta_ad_account_id and (latest is None or latest.meta_transport_ok is None):
            notes.append(
                "Pixelul Meta nu e încă în testul E2E: nu îl pot verifica direct, doar prin "
                "comenzile și apelurile atribuite reclamelor."
            )
        return TechnicalSignals(
            domain=account.target_domain.strip(),
            today=today,
            streams=streams,
            mobile_speed=speeds[0] if speeds else None,
            previous_mobile_speed=speeds[1] if len(speeds) > 1 else None,
            evidence=_synthetic_evidence(latest) if latest is not None else None,
            notes=notes,
            site_audit=_site_audit(audit) if audit is not None else None,
        )


def _mobile_speed(sample: SiteSpeedSample) -> MobileSpeed:
    return MobileSpeed(
        url=sample.url,
        measured_at=sample.measured_at,
        performance_score=sample.performance_score,
        lcp_ms=sample.lcp_ms,
        cls=sample.layout_shift,
        tbt_ms=sample.tbt_ms,
        field_lcp_ms=sample.field_lcp_ms,
        field_cls=sample.field_cls,
        field_inp_ms=sample.field_inp_ms,
    )


_AUDIT_SEVERITIES: dict[str, AuditSeverity] = {
    "critical": "critical", "warning": "warning", "info": "info"
}


def _site_audit(row: SiteAuditSnapshot) -> SiteAudit:
    issues = [
        AuditIssue(
            title=str(item.get("title", "")),
            severity=_AUDIT_SEVERITIES[str(item.get("severity"))],
            pages=int(item.get("pages", 0)),
            fix=str(item.get("fix", "")),
        )
        for item in row.top_issues
        if isinstance(item, dict)
        and item.get("title")
        and str(item.get("severity")) in _AUDIT_SEVERITIES
    ]
    return SiteAudit(
        audited_at=_utc(row.audited_at),
        url=row.url,
        pages_crawled=row.pages_crawled,
        completed=row.completed,
        seo_score=row.seo_score,
        geo_score=row.geo_score,
        critical=row.critical_issues,
        warnings=row.warning_issues,
        issues=issues,
    )


def _synthetic_evidence(row: TrackingEvidence) -> SyntheticEvidence:
    verdict = row.evidence.get("verdict") or {}

    def _expected(platform: str) -> tuple[str, ...]:
        return tuple((verdict.get(platform) or {}).get("expected_events") or ())

    return SyntheticEvidence(
        started_at=row.started_at,
        url=row.url,
        navigation_status=row.navigation_status,
        cta_selector=row.cta_selector,
        cta_ok=row.cta_ok,
        ga4_ok=row.ga4_transport_ok,
        meta_ok=row.meta_transport_ok,
        failure_reason=row.failure_reason,
        ga4_events=_expected("ga4"),
        meta_events=_expected("meta"),
    )


class ClientMarketSignals:
    """:class:`~ppc_agent_server.services.researcher.MarketIntelligenceSource` a unui client.

    Doar surse reale, pe nisa si orasul din ``queries`` (cautarile clientului), in
    paralel: interesul de cautare din Google Trends (``trends``) si cautarea pe web
    (abilitatea ``web_search``; ``verifier`` - Jev - pastreaza doar fragmentele despre
    nisa, ``None`` = toate). Fara cautari nu se deduce nisa, deci nu se cauta nimic.
    Licitatia si durerile din recenzii n-au inca sursa: raman goale (necunoscute).
    ``registry`` si ``trends`` sunt injectabile in teste.
    """

    def __init__(
        self,
        session: Session,
        *,
        today: Callable[[], date] = _utc_today,
        registry: SkillRegistry = skill_registry,
        verifier: RelevanceVerifier | None = None,
        trends: TrendsSource = google_trends,
        trends_wait: float = TRENDS_WAIT_SECONDS,
    ) -> None:
        self._session = session
        self._today = today
        self._registry = registry
        self._verifier = verifier
        self._trends = trends
        self._trends_wait = trends_wait

    def load(self, client_account_id: int, queries: Sequence[str] = ()) -> MarketSignals:
        account = self._session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        today = self._today()
        brand = _brand(account)
        country = "România" if account.geo.upper() == "RO" else account.geo
        niche, location = market_focus(queries, brand=brand, country=country)
        signals = MarketSignals(
            market=location,
            today=today,
            period_days=MARKET_PERIOD_DAYS,
            auction=None,
            demand=None,
            location=location,
        )
        if not niche:
            return replace(
                signals,
                web_note="Nișa nu se poate deduce încă (lipsesc căutările clientului): nu "
                "s-a căutat nici pe web, nici în Google Trends.",
            )
        (findings, status, note), (demand, trend_note) = asyncio.run(
            self._research(niche, location, geo=account.geo, country=country, year=today.year)
        )
        return replace(
            signals,
            market=f"{niche}, {location}",
            demand=demand,
            notes=[trend_note] if trend_note else [],
            niche=niche,
            web=findings,
            web_status=status,
            web_note=note,
        )

    async def _research(
        self, niche: str, location: str, *, geo: str, country: str, year: int
    ) -> tuple[tuple[list[WebFinding], WebStatus, str], tuple[DemandSeries | None, str]]:
        """Cautarea pe web si Google Trends, in paralel; niciuna nu arunca."""
        # Pe un executor propriu, nu pe cel implicit: ``asyncio.run`` asteapta la final
        # firele celui implicit, iar un Google Trends blocat ar tine Researcher-ul pe loc
        # dincolo de ``trends_wait``.
        trend = asyncio.get_running_loop().run_in_executor(
            _TRENDS_POOL,
            partial(load_trend_demand, self._trends, niche, geo=geo, country=country),
        )
        web, demand = await asyncio.gather(
            search_market_web(
                niche, location, year=year, registry=self._registry, verifier=self._verifier
            ),
            asyncio.wait_for(trend, self._trends_wait),
            return_exceptions=True,
        )
        if isinstance(web, BaseException):
            logger.warning("[Researcher] cautarea pe web a picat: %r", web)
            web = ([], "failed", "Căutarea pe web n-a răspuns acum.")
        if isinstance(demand, BaseException):
            logger.warning("[Researcher] Google Trends n-a raspuns la timp: %r", demand)
            demand = (
                None,
                f"Google Trends n-a răspuns în {self._trends_wait:.0f} s: trendul cererii rămâne "
                "necunoscut.",
            )
        return web, demand


def _proposal_topic(resource_type: str) -> str:
    kind = resource_type.lower()
    if "copy" in kind:
        return "creative"
    return "budget" if "budget" in kind or "campaign" in kind else "general"


class DbMemory:
    """:class:`~ppc_agent_server.services.memory.MemorySource` peste DB-ul serverului."""

    def __init__(self, session: Session, *, clock: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def recall(self, client_account_id: int, limit: int = HISTORY_LIMIT) -> list[MemoryEntry]:
        """Cele mai recente ``limit`` intrari: memoria consiliului si propunerile care n-au mers."""
        rows = self._session.exec(
            select(MemoryStream)
            .where(MemoryStream.client_account_id == client_account_id)
            .order_by(MemoryStream.timestamp.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all()
        since = self._clock() - timedelta(days=FAILED_LOOKBACK_DAYS)
        proposals = self._session.exec(
            select(ProposedChange)
            .where(ProposedChange.client_account_id == client_account_id)
            .where(ProposedChange.status.in_((ChangeStatus.REJECTED, ChangeStatus.FAILED)))  # type: ignore[attr-defined]
            .where(ProposedChange.created_at >= since)
            .order_by(ProposedChange.created_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all()
        entries = [
            MemoryEntry(
                at=row.timestamp,
                role=_role(row.agent_role),
                topic=row.topic,
                decision=row.decision,
                observation=row.observation,
                code=row.code,
            )
            for row in rows
        ]
        entries.extend(
            MemoryEntry(
                at=proposal.decided_at or proposal.created_at,
                role="queen" if proposal.source_module == "queen_agent" else "cfo",
                topic=_proposal_topic(proposal.resource_type),
                decision=compress(proposal.rationale),
                observation=compress(proposal.error_message or ""),
                outcome="rejected" if proposal.status == ChangeStatus.REJECTED else "failed",
            )
            for proposal in proposals
        )
        entries.sort(key=lambda entry: _utc(entry.at), reverse=True)
        return entries[:limit]

    def decisions(self, client_account_id: int, since: datetime) -> list[MemoryEntry]:
        """Deciziile cu cod (veto, taieturi) de la ``since`` - pentru jobul PPC de noapte."""
        rows = self._session.exec(
            select(MemoryStream)
            .where(MemoryStream.client_account_id == client_account_id)
            .where(MemoryStream.timestamp >= since)
            .where(col(MemoryStream.code).is_not(None))
            .order_by(MemoryStream.timestamp.desc())  # type: ignore[attr-defined]
        ).all()
        return [
            MemoryEntry(
                at=row.timestamp,
                role=_role(row.agent_role),
                topic=row.topic,
                decision=row.decision,
                observation=row.observation,
                code=row.code,
            )
            for row in rows
        ]

    def remember(self, client_account_id: int, entries: Sequence[MemoryEntry]) -> None:
        """Scrie intrarile noi; aceeasi decizie a aceluiasi rol, din ultimele 7 zile, se sare."""
        for entry in entries:
            recent = self._session.exec(
                select(MemoryStream.id)
                .where(MemoryStream.client_account_id == client_account_id)
                .where(MemoryStream.agent_role == entry.role)
                .where(MemoryStream.decision == entry.decision)
                .where(MemoryStream.timestamp >= entry.at - timedelta(days=DEDUPE_DAYS))
            ).first()
            if recent is not None:
                continue
            self._session.add(
                MemoryStream(
                    client_account_id=client_account_id,
                    timestamp=entry.at,
                    agent_role=entry.role,
                    topic=entry.topic,
                    observation=entry.observation,
                    decision=entry.decision,
                    code=entry.code,
                )
            )
        self._session.commit()


_ROLES: dict[str, AgentRole] = {
    "queen": "queen", "cfo": "cfo", "cto": "cto", "cso": "cso", "cpo": "cpo"
}


def _role(value: str) -> AgentRole:
    return _ROLES.get(value, "queen")


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
