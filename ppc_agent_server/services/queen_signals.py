"""Semnalele Reginei pentru un client real: baza de date + Search Console.

Singurul loc care stie de unde vin datele Reginei - ``queen_agent.py`` ramane
pur si le primeste gata adunate (:class:`~ppc_agent_server.services.queen_agent.BrandSignals`):

- **cautarile organice** vin de la agentul SEO/GEO (``seo_intelligence``), dar
  DOAR cand Search Console e conectat (``live``). Datele demonstrative ale
  paginii "Trafic & Pozitii" (un service auto inventat) nu au voie sa ajunga
  intr-o directiva pentru un client real;
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
  apelurile din ``ConversionEvent`` (pe sursa webhook-ului) - si ultima
  masuratoare PageSpeed pe mobil (``SiteSpeedSample``);
- **piata** (pentru Researcher, ``researcher.py``): licitatia, cererea si
  mentiunile sunt demonstrative (``market_demo.py``) - nu exista inca surse; cautarea
  pe web e reala, pe nisa si orasul scoase din cautarile clientului.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

import httpx
from sqlmodel import Session, select

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
    ProposedChange,
    SearchTermConversion,
    SiteSpeedSample,
)
from ppc_agent_server.services.council import AdSpend, FinancialSignals, TermSpend
from ppc_agent_server.services.market_demo import demo_market_signals
from ppc_agent_server.services.queen_agent import BrandSignals, LiveAd, SearchSignal
from ppc_agent_server.services.researcher import (
    MarketSignals,
    WebSearch,
    market_focus,
    search_market_web,
)
from ppc_agent_server.services.technician import (
    DailyConversions,
    MobileSpeed,
    TechnicalSignals,
    TrackingStream,
)
from seo_geo_agent.audit.geo_reporters import brand_token_from_url
from seo_geo_agent.services.intelligence import Window

#: Fereastra de cautari organice - aceeasi ca implicita paginii "Trafic & Pozitii".
ORGANIC_WINDOW_DAYS = 28


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
                conversions=record.conversions if record else None,
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
        days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        self._session = session
        self._seo_intent = seo_intent or SearchConsoleIntent()
        self._days = days

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
        )


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
        records = self._session.exec(
            select(AdPerformanceRecord).where(
                AdPerformanceRecord.client_account_id == client_account_id
            )
        ).all()
        terms = load_paid_terms(self._session, client_account_id, days=self._days)
        pending = self._session.exec(
            select(ProposedChange.id)
            .where(ProposedChange.client_account_id == client_account_id)
            .where(ProposedChange.status == ChangeStatus.PENDING)
        ).all()
        notes: list[str] = []
        if not records and not terms:
            notes.append(
                "Nicio cheltuială înregistrată: nici reclame Meta/TikTok cu performanță, nici "
                f"termeni Google Ads în ultimele {self._days} de zile."
            )
        return FinancialSignals(
            objective=account.objective.value,
            ads=[
                AdSpend(
                    ad_id=record.ad_id,
                    platform=record.platform.value,
                    label=headlines.get(record.ad_id, ""),
                    spend=record.spend,
                    conversions=record.conversions,
                    revenue=record.revenue,
                    target_cpa=record.target_cpa,
                )
                for record in records
            ],
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
        )


def _utc_today() -> date:
    return datetime.now(tz=UTC).date()


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

        sample = self._session.exec(
            select(SiteSpeedSample)
            .where(SiteSpeedSample.client_account_id == client_account_id)
            .order_by(SiteSpeedSample.measured_at.desc())  # type: ignore[attr-defined]
        ).first()
        notes: list[str] = []
        if account.meta_ad_account_id:
            notes.append(
                "Pixelul Meta nu trimite încă o serie zilnică de conversii în platformă: nu îl "
                "pot verifica direct, doar prin comenzile și apelurile atribuite reclamelor."
            )
        return TechnicalSignals(
            domain=account.target_domain.strip(),
            today=today,
            streams=streams,
            mobile_speed=(
                MobileSpeed(
                    url=sample.url,
                    measured_at=sample.measured_at,
                    performance_score=sample.performance_score,
                    lcp_ms=sample.lcp_ms,
                    cls=sample.layout_shift,
                    tbt_ms=sample.tbt_ms,
                )
                if sample is not None
                else None
            ),
            notes=notes,
        )


class ClientMarketSignals:
    """:class:`~ppc_agent_server.services.researcher.MarketIntelligenceSource` a unui client.

    Licitatia, cererea si mentiunile: demonstrative (seed = brandul, stabile toata
    ziua, marcate ``source="demo"``) - nu exista inca API-uri pentru ele. Cautarea
    pe web: reala, pe nisa si orasul din ``queries`` (cautarile clientului); fara
    cautari, nu se cauta nimic. ``search`` e injectabil in teste.
    """

    def __init__(
        self,
        session: Session,
        *,
        today: Callable[[], date] = _utc_today,
        search: WebSearch | None = None,
    ) -> None:
        self._session = session
        self._today = today
        self._search = search

    def load(self, client_account_id: int, queries: Sequence[str] = ()) -> MarketSignals:
        account = self._session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        today = self._today()
        brand = _brand(account)
        signals = demo_market_signals(brand or account.name or str(client_account_id), today)
        country = "România" if account.geo.upper() == "RO" else account.geo
        niche, location = market_focus(queries, brand=brand, country=country)
        if not niche:
            return replace(
                signals,
                location=location,
                web_note="Nișa nu se poate deduce încă (lipsesc căutările clientului): nu "
                "s-a căutat pe web.",
            )
        findings, status, note = asyncio.run(
            search_market_web(niche, location, year=today.year, search=self._search)
        )
        return replace(
            signals, niche=niche, location=location, web=findings, web_status=status, web_note=note
        )
