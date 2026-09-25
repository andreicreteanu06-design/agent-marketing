"""Orchestrarea unui audit: descoperire -> crawl -> verificari -> scoruri.

Echivalentul lui ``SiteAuditWorkflow`` din ``every-app/open-seo``, redus la ce
are sens fara Cloudflare Workflows: acolo fiecare pas e un checkpoint durabil
pentru ca un audit de 500 de pagini depaseste limitele unui singur request;
aici auditul ruleaza ca task asyncio in proces, cu un buget de pagini SI unul de
timp, iar starea lui traieste in ``store.py``.

Ce ramane identic, fiindca de asta depinde corectitudinea raportului:

- crawl-ul respecta robots.txt pentru user-agent-ul propriu;
- nu iese niciodata din originea de start (``is_same_origin``), iar fiecare URL
  descoperit trece din nou prin politica anti-SSRF;
- redirecturile sunt urmarite manual, salt cu salt, ca lanturile sa fie vizibile;
- daca bugetul se termina inainte de coada, auditul se marcheaza TRUNCHIAT, iar
  verificarile care au nevoie de un graf complet (paginile orfane) nu ruleaza.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from seo_geo_agent.audit.crawler import CRAWL_HEADERS, crawl_page, fetch_text_file
from seo_geo_agent.audit.discovery import discover_urls
from seo_geo_agent.audit.geo_reporters import (
    brand_token_from_url,
    run_geo_page_reporters,
    run_geo_site_reporters,
)
from seo_geo_agent.audit.issues import IssuePillar
from seo_geo_agent.audit.multipage import run_multipage_checks
from seo_geo_agent.audit.page_reporters import DetectedIssue, run_page_reporters
from seo_geo_agent.audit.robots import RobotsTxt, parse_robots_txt
from seo_geo_agent.audit.safe_transport import SafeAsyncTransport
from seo_geo_agent.audit.scoring import PillarScore, compute_pillar_scores
from seo_geo_agent.audit.types import CRAWL_USER_AGENT, CrawledPage
from seo_geo_agent.audit.url_policy import is_crawlable_url
from seo_geo_agent.audit.url_utils import (
    canonical_url_key,
    get_origin,
    is_same_origin,
    normalize_url,
)

logger = logging.getLogger("seo_geo_agent.audit.service")

_MAX_ROBOTS_TXT_BYTES = 500 * 1024
_MAX_LLMS_TXT_BYTES = 64 * 1024
#: Redirecturi urmate pentru URL-ul de start: http->https si apex->www incap lejer.
_MAX_START_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class AuditConfig:
    """Bugetele unui audit. Praguri, nu preferinte: le respecta strict."""

    max_pages: int = 25
    #: Cereri in paralel catre acelasi site. 5 e politicos si suficient; peste,
    #: site-urile mici incep sa raspunda 429 si raportul devine despre noi.
    concurrency: int = 5
    #: Dupa expirarea lui, crawl-ul se opreste si auditul se marcheaza trunchiat.
    time_budget_seconds: float = 150.0
    #: Numele exact al brandului, daca il stie clientul. Gol => se deduce din domeniu.
    brand: str = ""


@dataclass(slots=True)
class AuditProgress:
    """Ce se poate arata in UI cat timp auditul ruleaza."""

    crawled: int = 0
    queued: int = 0
    max_pages: int = 0


@dataclass(slots=True)
class AuditResult:
    """Raportul complet: paginile crawlate, problemele gasite si scorurile."""

    start_url: str
    origin: str
    brand: str
    started_at: datetime
    finished_at: datetime
    #: ``False`` = crawl-ul s-a oprit din buget (pagini sau timp), nu din coada goala.
    completed: bool
    robots_txt_found: bool
    llms_txt_found: bool
    sitemap_urls_found: int
    pages: list[CrawledPage] = field(default_factory=list)
    issues: list[DetectedIssue] = field(default_factory=list)
    scores: dict[IssuePillar, PillarScore] = field(default_factory=dict)


class _Frontier:
    """Coada de URL-uri de crawlat, cu deduplicare globala.

    Paginile din sitemap intra cu ``depth=None`` (nu s-a ajuns la ele prin
    linkuri), ca verificarea ``deep-page`` sa nu inventeze o adancime pe care
    nu a masurat-o nimeni.
    """

    def __init__(self) -> None:
        self._pending: list[tuple[str, int | None, bool]] = []
        self._seen: set[str] = set()

    def add(self, url: str, depth: int | None, *, in_sitemap: bool) -> None:
        if url in self._seen:
            return
        self._seen.add(url)
        self._pending.append((url, depth, in_sitemap))

    def take(self, count: int) -> list[tuple[str, int | None, bool]]:
        batch = self._pending[:count]
        del self._pending[:count]
        return batch

    def __len__(self) -> int:
        return len(self._pending)


async def _fetch_site_files(
    client: httpx.AsyncClient, origin: str
) -> tuple[RobotsTxt, bool]:
    """robots.txt (parsat) si prezenta lui /llms.txt - ambele optionale."""
    robots_text, llms_text = await asyncio.gather(
        fetch_text_file(client, f"{origin}/robots.txt", max_bytes=_MAX_ROBOTS_TXT_BYTES),
        fetch_text_file(client, f"{origin}/llms.txt", max_bytes=_MAX_LLMS_TXT_BYTES),
    )
    return parse_robots_txt(robots_text), bool(llms_text and llms_text.strip())


async def _resolve_start_url(client: httpx.AsyncClient, start_url: str) -> str:
    """URL-ul la care raspunde de fapt site-ul, urmand redirecturile URL-ului de start.

    ``exemplu.ro`` -> ``https://www.exemplu.ro/`` e cazul obisnuit. Fara pasul
    asta, originea auditului ramanea domeniul tastat, iar robots.txt, llms.txt
    si sitemap-ul se cereau acolo unde site-ul raspunde doar cu redirect - deci
    "lipseau", desi exista.

    Se urmeaza doar redirecturi in aceeasi granita de crawl (``is_same_origin``:
    cu/fara ``www.``, upgrade la https) si catre URL-uri crawlabile - aceeasi
    politica pe care o trec si linkurile descoperite. Un redirect spre alt
    domeniu sau o eroare de retea lasa URL-ul de start neschimbat; crawl-ul il
    raporteaza apoi ca de obicei.
    """
    origin = get_origin(start_url)
    current = start_url
    for _ in range(_MAX_START_REDIRECTS):
        try:
            request = client.build_request("GET", current, headers=CRAWL_HEADERS)
            response = await client.send(request, stream=True, follow_redirects=False)
            await response.aclose()
        except (httpx.HTTPError, UnicodeError, ValueError):
            return current
        location = response.headers.get("location")
        if not (300 <= response.status_code < 400 and location):
            return current
        target = normalize_url(location, current)
        if target is None or not is_same_origin(target, origin) or not is_crawlable_url(target):
            return current
        current = target
    return current


def _should_crawl(url: str, origin: str, robots: RobotsTxt) -> bool:
    """Filtrul prin care trece FIECARE URL, indiferent de unde a fost descoperit."""
    return (
        is_same_origin(url, origin)
        and is_crawlable_url(url)
        and robots.is_allowed(url, CRAWL_USER_AGENT)
    )


async def run_audit(
    start_url: str,
    config: AuditConfig,
    on_progress: Callable[[AuditProgress], None] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AuditResult:
    """Ruleaza auditul complet pentru ``start_url`` si intoarce raportul.

    ``start_url`` trebuie sa fie deja validat cu
    :func:`seo_geo_agent.audit.url_policy.normalize_and_validate_start_url` -
    functia asta nu re-verifica politica pentru URL-ul de start (o face pentru
    tot ce descopera pe parcurs).

    ``transport`` exista pentru teste: cu un ``httpx.MockTransport`` intreg
    motorul (descoperire, crawl, verificari, scoruri) se poate rula pe un site
    fals, fara retea - acelasi tipar ca in ``seo_geo_agent/external_data.py``.
    """
    started_at = datetime.now(tz=UTC)
    deadline = time.monotonic() + config.time_budget_seconds

    pages: list[CrawledPage] = []
    frontier = _Frontier()

    limits = httpx.Limits(
        max_connections=config.concurrency, max_keepalive_connections=config.concurrency
    )
    # Scutul SSRF (``safe_transport``) verifica IP-ul la FIECARE cerere - start,
    # redirecturi, sitemap-uri, linkuri. Testele isi aduc propriul transport.
    async with httpx.AsyncClient(
        timeout=15.0,
        limits=limits,
        follow_redirects=False,
        transport=transport or SafeAsyncTransport(limits=limits),
    ) as client:
        # Tot auditul (origine, fisierele site-ului, pagina principala) porneste
        # de unde raspunde site-ul, nu de la forma tastata a domeniului.
        start_url = await _resolve_start_url(client, start_url)
        origin = get_origin(start_url)
        brand = config.brand.strip() or brand_token_from_url(start_url)
        frontier.add(start_url, 0, in_sitemap=False)

        robots, llms_txt_found = await _fetch_site_files(client, origin)

        sitemap_urls = await discover_urls(client, origin, robots, config.max_pages)
        for url in sitemap_urls:
            frontier.add(url, None, in_sitemap=True)

        def report_progress() -> None:
            if on_progress is not None:
                on_progress(
                    AuditProgress(
                        crawled=len(pages), queued=len(frontier), max_pages=config.max_pages
                    )
                )

        report_progress()
        while len(frontier) > 0 and len(pages) < config.max_pages:
            if time.monotonic() >= deadline:
                break
            batch = frontier.take(min(config.concurrency, config.max_pages - len(pages)))
            allowed = [item for item in batch if _should_crawl(item[0], origin, robots)]
            if not allowed:
                continue

            results = await asyncio.gather(
                *(
                    crawl_page(client, url, crawl_depth=depth, in_sitemap=in_sitemap)
                    for url, depth, in_sitemap in allowed
                )
            )
            pages.extend(results)

            for page in results:
                next_depth = None if page.crawl_depth is None else page.crawl_depth + 1
                if page.redirect_url:
                    frontier.add(page.redirect_url, page.crawl_depth, in_sitemap=False)
                for link in page.links:
                    if link.is_internal:
                        frontier.add(link.target_url, next_depth, in_sitemap=False)
            report_progress()

    completed = len(frontier) == 0 and len(pages) <= config.max_pages
    if time.monotonic() >= deadline and len(frontier) > 0:
        completed = False

    issues: list[DetectedIssue] = []
    for page in pages:
        issues.extend(run_page_reporters(page))
        issues.extend(run_geo_page_reporters(page, brand))
    issues.extend(run_multipage_checks(pages, start_url, crawl_completed=completed))

    start_key = canonical_url_key(start_url)
    homepage = next((page for page in pages if canonical_url_key(page.url) == start_key), None)
    issues.extend(
        run_geo_site_reporters(
            start_url, robots, homepage=homepage, llms_txt_found=llms_txt_found
        )
    )

    # Daca site-ul ne-a limitat si crawl-ul nu a terminat coada, spunem explicit
    # ca raportul e incomplet - originalul face exact asta (``crawl-rate-limited``).
    if not completed and any(page.fetch_class == "rate_limited" for page in pages):
        issues.append(DetectedIssue(issue_type="crawl-rate-limited", page_url=start_url))

    return AuditResult(
        start_url=start_url,
        origin=origin,
        brand=brand,
        started_at=started_at,
        finished_at=datetime.now(tz=UTC),
        completed=completed,
        robots_txt_found=robots.fetched,
        llms_txt_found=llms_txt_found,
        sitemap_urls_found=len(sitemap_urls),
        pages=pages,
        issues=issues,
        scores=compute_pillar_scores(pages, issues),
    )
