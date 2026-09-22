"""Descoperirea URL-urilor din robots.txt si sitemap.xml.

Portare a ``src/server/lib/audit/discovery.ts`` din ``every-app/open-seo``,
cu aceleasi plafoane (adancime 3 pentru index-uri imbricate, 300 de documente,
5 descarcari in paralel, 10 MB per document) si cu aceeasi regula de siguranta:
orice sitemap care iese din origine e ignorat.

Un sitemap care esueaza nu opreste auditul - crawl-ul continua din pagina de
start, prin linkuri. De aceea functia nu ridica niciodata exceptii.
"""

from __future__ import annotations

import asyncio
import logging
from xml.etree import ElementTree

import httpx

from seo_geo_agent.audit.robots import RobotsTxt
from seo_geo_agent.audit.types import CRAWL_USER_AGENT
from seo_geo_agent.audit.url_utils import is_same_origin, normalize_url

logger = logging.getLogger("seo_geo_agent.audit.discovery")

_MAX_SITEMAP_DEPTH = 3
_MAX_SITEMAP_DOCS = 300
_SITEMAP_CONCURRENCY = 5
_MAX_SITEMAP_BYTES = 10 * 1024 * 1024
_SITEMAP_TIMEOUT_SECONDS = 15.0


def _local_name(tag: str) -> str:
    """Numele tagului fara namespace (``{http://...}url`` -> ``url``)."""
    return tag.rsplit("}", 1)[-1]


def _extract_locations(root: ElementTree.Element) -> tuple[list[str], list[str]]:
    """Intoarce ``(sitemap-uri imbricate, URL-uri de pagini)`` dintr-un document XML."""
    nested: list[str] = []
    pages: list[str] = []
    root_name = _local_name(root.tag)
    for child in root:
        child_name = _local_name(child.tag)
        loc = next((el.text for el in child if _local_name(el.tag) == "loc"), None)
        if not loc or not loc.strip():
            continue
        if root_name == "sitemapindex" and child_name == "sitemap":
            nested.append(loc.strip())
        elif root_name == "urlset" and child_name == "url":
            pages.append(loc.strip())
    return nested, pages


async def _fetch_sitemap_document(
    client: httpx.AsyncClient, sitemap_url: str
) -> tuple[list[str], list[str]]:
    """Descarca si parseaza un sitemap. Orice esec => doua liste goale."""
    try:
        response = await client.get(
            sitemap_url,
            headers={"User-Agent": CRAWL_USER_AGENT},
            timeout=_SITEMAP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("sitemap inaccesibil %s: %s", sitemap_url, exc)
        return [], []

    if response.status_code != 200:
        return [], []
    final_url = normalize_url(str(response.url), sitemap_url)
    if final_url is None or not is_same_origin(final_url, sitemap_url):
        return [], []  # un redirect in afara originii nu e sitemap-ul nostru

    body = response.content[:_MAX_SITEMAP_BYTES]
    if len(response.content) > _MAX_SITEMAP_BYTES:
        return [], []  # XML taiat nu s-ar parsa oricum
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return [], []

    nested_raw, pages_raw = _extract_locations(root)
    nested = [url for url in (normalize_url(loc, final_url) for loc in nested_raw) if url]
    pages = [url for url in (normalize_url(loc, final_url) for loc in pages_raw) if url]
    return nested, pages


async def discover_urls(
    client: httpx.AsyncClient, origin: str, robots: RobotsTxt, max_pages: int
) -> list[str]:
    """URL-urile de pagini declarate de site, din sitemap-urile lui.

    Sursele sunt sitemap-urile listate in robots.txt plus locatia implicita
    ``/sitemap.xml``. Rezultatul e plafonat la bugetul de pagini al auditului:
    astea sunt doar seminte, crawl-ul nu poate folosi mai multe.
    """
    sources = list(dict.fromkeys([*robots.sitemaps, f"{origin}/sitemap.xml"]))
    queue: list[tuple[str, int]] = []
    for raw in sources:
        normalized = normalize_url(raw, origin)
        if normalized and is_same_origin(normalized, origin):
            queue.append((normalized, _MAX_SITEMAP_DEPTH))

    discovered: dict[str, None] = {}
    seen_docs: set[str] = set()
    fetched_docs = 0
    max_discovered = min(max(max_pages * 20, 500), 50_000)

    while queue and len(discovered) < max_discovered and fetched_docs < _MAX_SITEMAP_DOCS:
        batch = [item for item in queue[:_SITEMAP_CONCURRENCY]]
        del queue[:_SITEMAP_CONCURRENCY]
        batch = [(url, depth) for url, depth in batch if depth > 0 and url not in seen_docs]
        if not batch:
            continue
        seen_docs.update(url for url, _ in batch)
        fetched_docs += len(batch)

        results = await asyncio.gather(
            *(_fetch_sitemap_document(client, url) for url, _ in batch)
        )
        for (_, depth), (nested, pages) in zip(batch, results, strict=True):
            for page_url in pages:
                if len(discovered) >= max_discovered:
                    break
                if is_same_origin(page_url, origin):
                    discovered[page_url] = None
            if depth <= 1:
                continue
            for nested_url in nested:
                if is_same_origin(nested_url, origin) and nested_url not in seen_docs:
                    queue.append((nested_url, depth - 1))

    return list(discovered)[:max_pages]
