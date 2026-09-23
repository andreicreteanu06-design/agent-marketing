"""Descarcarea unei pagini si clasificarea onesta a raspunsului.

Portare a ``src/server/workflows/site-audit-workflow-helpers.ts`` din
``every-app/open-seo``. Regula lui centrala, pastrata ca atare: cand site-ul ne
opreste (challenge anti-bot, 403, 429), NU inregistram pagina ca "stricata" -
o marcam ``blocked``/``rate_limited`` si o spunem in raport. Un raport care
minte despre ce a putut si ce nu a putut masura nu valoreaza nimic.

Redirecturile se urmaresc MANUAL (``follow_redirects=False``): fiecare salt e
inregistrat ca pagina proprie, iar tinta lui intra in coada. Doar asa devin
lanturile si buclele de redirect detectabile din randurile inregistrate
(vezi ``multipage.py``).
"""

from __future__ import annotations

import hashlib
import logging
import time

import httpx

from seo_geo_agent.audit.page_analyzer import analyze_html
from seo_geo_agent.audit.types import CRAWL_USER_AGENT, CrawledPage, PageFetchClass
from seo_geo_agent.audit.url_utils import normalize_url

logger = logging.getLogger("seo_geo_agent.audit.crawler")

#: Plafonul de octeti cititi dintr-o pagina. Public fiindca il refoloseste si
#: crawler-ul live al agentului PPC (``ppc_agent/providers/live/crawler.py``):
#: aceeasi limita, nu doua valori care pot diverge.
MAX_HTML_BYTES = 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 15.0

#: Semne ale unei pagini de provocare anti-bot. Le clasificam onest ca
#: "blocked", in loc sa inregistram HTML-ul provocarii ca si cum ar fi pagina.
_CHALLENGE_BODY_MARKERS = (
    "just a moment...",
    "challenge-platform",
    "cf-browser-verification",
    "attention required! | cloudflare",
    "verifying you are human",
)

CRAWL_HEADERS = {
    "User-Agent": CRAWL_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
}


def classify_fetch(status_code: int, headers: httpx.Headers, body_snippet: str) -> PageFetchClass:
    """Traduce raspunsul HTTP in una dintre cele patru clase de descarcare."""
    if status_code == 0:
        return "error"
    # Un 429 final inseamna limitare de rata, fie ca reincercarile s-au
    # epuizat, fie ca racirea ceruta depasea bugetul. Verificat INAINTEA lui
    # cf-mitigated: o regula Cloudflare de rate-limiting seteaza si acel antet.
    if status_code == 429:
        return "rate_limited"
    if headers.get("cf-mitigated"):
        return "blocked"
    if status_code in (401, 403):
        return "blocked"
    if status_code == 503:
        snippet = body_snippet.lower()
        if any(marker in snippet for marker in _CHALLENGE_BODY_MARKERS):
            return "blocked"
    return "ok"


def parse_link_header_canonical(link_header: str | None, page_url: str) -> str | None:
    """Extrage ``<url>; rel="canonical"`` din antetul HTTP ``Link``."""
    if not link_header:
        return None
    for part in link_header.split(","):
        start, sep, rest = part.partition(">")
        if not sep or "<" not in start:
            continue
        if "canonical" in rest.lower().replace('"', "").replace(" ", ""):
            return normalize_url(start[start.index("<") + 1 :].strip(), page_url)
    return None


async def read_text_up_to(response: httpx.Response, max_bytes: int) -> tuple[str, int]:
    """Citeste corpul raspunsului pana la ``max_bytes``; intoarce textul si octetii cititi.

    Plafonul exista pentru ca primul MiB contine oricum metadatele SEO si
    navigatia de care are nevoie auditul, iar o pagina de 50 MB nu trebuie sa
    poata umple memoria procesului.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    raw = b"".join(chunks)[:max_bytes]
    return raw.decode(response.encoding or "utf-8", errors="replace"), len(raw)


def _empty_page(
    url: str,
    status_code: int,
    fetch_class: PageFetchClass,
    *,
    redirect_url: str | None = None,
    response_time_ms: int = 0,
    x_robots_tag: str | None = None,
    header_canonical_url: str | None = None,
    html_bytes: int = 0,
    crawl_depth: int | None = None,
    in_sitemap: bool = False,
) -> CrawledPage:
    """Pagina inregistrata fara analiza de continut (redirect, non-HTML, eroare)."""
    return CrawledPage(
        url=url,
        status_code=status_code,
        fetch_class=fetch_class,
        redirect_url=redirect_url,
        x_robots_tag=x_robots_tag,
        header_canonical_url=header_canonical_url,
        html_bytes=html_bytes,
        is_indexable=False,
        response_time_ms=response_time_ms,
        crawl_depth=crawl_depth,
        in_sitemap=in_sitemap,
    )


async def crawl_page(
    client: httpx.AsyncClient,
    url: str,
    *,
    crawl_depth: int | None,
    in_sitemap: bool,
) -> CrawledPage:
    """Descarca si analizeaza o singura pagina. Nu ridica exceptii de retea.

    Orice esec (timeout, DNS, conexiune resetata) devine o pagina cu
    ``fetch_class="error"`` si status 0 - auditul continua, iar raportul spune
    ce nu s-a putut citi.
    """
    started = time.monotonic()
    try:
        request = client.build_request("GET", url, headers=CRAWL_HEADERS)
        response = await client.send(request, stream=True, follow_redirects=False)
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        logger.warning("crawl esuat pentru %s: %s", url, exc)
        return _empty_page(
            url,
            0,
            "error",
            response_time_ms=int((time.monotonic() - started) * 1000),
            crawl_depth=crawl_depth,
            in_sitemap=in_sitemap,
        )

    try:
        response_time_ms = int((time.monotonic() - started) * 1000)
        status_code = response.status_code
        # De aici incolo, un esec de citire (timeout la stream, conexiune
        # rupta la jumatatea corpului) e tot o pagina "error", nu o exceptie
        # care opreste auditul.
        x_robots_tag = response.headers.get("x-robots-tag")
        header_canonical_url = parse_link_header_canonical(response.headers.get("link"), url)

        if 300 <= status_code < 400:
            location = response.headers.get("location")
            return _empty_page(
                url,
                status_code,
                "ok",
                redirect_url=normalize_url(location, url) if location else None,
                response_time_ms=response_time_ms,
                x_robots_tag=x_robots_tag,
                header_canonical_url=header_canonical_url,
                crawl_depth=crawl_depth,
                in_sitemap=in_sitemap,
            )

        is_html = "text/html" in (response.headers.get("content-type") or "")
        try:
            body, html_bytes = (
                await read_text_up_to(response, MAX_HTML_BYTES) if is_html else ("", 0)
            )
        except httpx.HTTPError as exc:
            logger.warning("citirea corpului a esuat pentru %s: %s", url, exc)
            return _empty_page(
                url,
                0,
                "error",
                response_time_ms=response_time_ms,
                crawl_depth=crawl_depth,
                in_sitemap=in_sitemap,
            )
        fetch_class = classify_fetch(status_code, response.headers, body[:4000])

        if not is_html or fetch_class != "ok" or status_code >= 400:
            return _empty_page(
                url,
                status_code,
                fetch_class,
                response_time_ms=response_time_ms,
                x_robots_tag=x_robots_tag,
                header_canonical_url=header_canonical_url,
                html_bytes=html_bytes,
                crawl_depth=crawl_depth,
                in_sitemap=in_sitemap,
            )
    finally:
        await response.aclose()

    analysis = analyze_html(body, url)
    directives = ",".join(filter(None, (analysis.robots_meta, x_robots_tag))).lower()
    canonical_url = (
        normalize_url(analysis.canonical, url) or analysis.canonical if analysis.canonical else None
    )
    return CrawledPage(
        url=url,
        status_code=status_code,
        fetch_class=fetch_class,
        title=analysis.title,
        meta_description=analysis.meta_description,
        canonical_url=canonical_url,
        robots_meta=analysis.robots_meta,
        x_robots_tag=x_robots_tag,
        header_canonical_url=header_canonical_url,
        og_title=analysis.og_title,
        og_description=analysis.og_description,
        og_image=analysis.og_image,
        meta_author=analysis.meta_author,
        h1_count=len([h for h in analysis.h1s if h]),
        heading_order=analysis.heading_order,
        headings=analysis.headings,
        word_count=analysis.word_count,
        body_text=analysis.body_text,
        content_hash=(
            hashlib.sha256(analysis.body_text.encode("utf-8")).hexdigest()
            if analysis.body_text
            else None
        ),
        is_html=True,
        html_bytes=html_bytes,
        images_total=len(analysis.images),
        # Doar un atribut alt ABSENT conteaza: alt="" e marcajul corect pentru
        # imaginile pur decorative.
        images_missing_alt=len([img for img in analysis.images if img[1] is None]),
        links=analysis.links,
        structured_data=analysis.structured_data,
        hreflang_tags=analysis.hreflang_tags,
        is_indexable="noindex" not in directives,
        response_time_ms=response_time_ms,
        crawl_depth=crawl_depth,
        in_sitemap=in_sitemap,
    )


async def fetch_text_file(client: httpx.AsyncClient, url: str, *, max_bytes: int) -> str | None:
    """Descarca un fisier text mic (robots.txt, llms.txt). ``None`` = lipseste/inaccesibil."""
    try:
        response = await client.get(url, headers={"User-Agent": CRAWL_USER_AGENT})
        if response.status_code != 200:
            return None
        return response.text[:max_bytes]
    except httpx.HTTPError as exc:
        logger.warning("nu am putut citi %s: %s", url, exc)
        return None
