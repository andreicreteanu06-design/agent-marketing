"""Verificarile care au nevoie de mai multe pagini deodata.

Portare a ``src/server/lib/audit/issues/multipage-checks.ts`` (duplicate,
lanturi/bucle de redirect) si a celor doua interogari SQL din
``src/server/features/audit/scratchpad-sql.ts`` (linkuri interne rupte, pagini
orfane) din ``every-app/open-seo``. Originalul le tine separat fiindca acolo
unele ruleaza pe D1 si altele intr-un Durable Object; aici tot setul de pagini
e deja in memorie, deci sunt simple functii pure peste el.

Doua reguli din original, pastrate cuvant cu cuvant in comportament, fiindca
ele fac diferenta intre un raport corect si unul care sperie degeaba:

- un link e "rupt" doar daca am crawlat NOI tinta si am vazut-o esuand; nu se
  deduce niciodata din absenta, iar tintele ``blocked`` (provocare anti-bot) nu
  se pun la socoteala - un 403 de la un WAF nu e dovada ca linkul e rupt;
- paginile orfane se raporteaza doar dupa un crawl COMPLET. Daca s-a atins
  bugetul de pagini, "nu are linkuri de intrare" inseamna date lipsa, nu dovada.
"""

from __future__ import annotations

from collections.abc import Callable

from seo_geo_agent.audit.page_reporters import DetectedIssue
from seo_geo_agent.audit.types import CrawledPage

_DUPLICATE_GROUP_SAMPLE = 3
_BROKEN_LINK_ISSUE_CAP = 2_000


def _is_ok_html_page(page: CrawledPage) -> bool:
    return page.fetch_class == "ok" and 200 <= page.status_code < 300


def _is_duplicate_candidate(page: CrawledPage) -> bool:
    """Paginile pe care proprietarul le-a deduplicat deja nu intra in grupuri.

    Un noindex sau un canonical catre alt URL inseamna ca problema e rezolvata;
    raportand-o, i-am cere sa repare ceva ce a reparat deja.
    """
    if not _is_ok_html_page(page) or not page.is_indexable:
        return False
    effective_canonical = page.canonical_url or page.header_canonical_url
    return not effective_canonical or effective_canonical == page.url


def find_duplicates(pages: list[CrawledPage]) -> list[DetectedIssue]:
    """Titluri, meta description si continut identice pe mai multe URL-uri."""
    candidates = [page for page in pages if _is_duplicate_candidate(page)]
    issues: list[DetectedIssue] = []

    def emit(key_of: Callable[[CrawledPage], str | None], issue_type: str) -> None:
        groups: dict[str, list[CrawledPage]] = {}
        for page in candidates:
            key = key_of(page)
            if not key:
                continue
            groups.setdefault(key, []).append(page)
        for group in groups.values():
            if len(group) < 2:
                continue
            for page in group:
                issues.append(
                    DetectedIssue(
                        issue_type=issue_type,
                        page_url=page.url,
                        details={
                            "group_size": len(group),
                            "other_urls": [
                                other.url for other in group if other.url != page.url
                            ][:_DUPLICATE_GROUP_SAMPLE],
                        },
                    )
                )

    emit(lambda page: page.title, "duplicate-title")
    emit(lambda page: page.meta_description, "duplicate-meta-description")
    emit(lambda page: page.content_hash if page.word_count > 0 else None, "duplicate-content")
    return issues


def find_redirect_chains_and_loops(pages: list[CrawledPage]) -> list[DetectedIssue]:
    """Lanturi de 2+ redirecturi si bucle care nu se termina niciodata."""
    redirects = {
        page.url: page
        for page in pages
        if 300 <= page.status_code < 400 and page.redirect_url
    }
    redirect_targets = {page.redirect_url for page in redirects.values()}

    issues: list[DetectedIssue] = []
    walked: set[str] = set()

    # Pornim din capetele de lant (redirecturi catre care nu redirecteaza nimic
    # altceva), ca un lant de 5 salturi sa dea o problema, nu cinci.
    for url, head in redirects.items():
        if url in redirect_targets:
            continue
        hops = [url]
        seen = {url}
        walked.add(url)
        current = head.redirect_url
        is_loop = False
        while current:
            if current in seen:
                is_loop = True
                hops.append(current)
                break
            hops.append(current)
            seen.add(current)
            if current in redirects:
                walked.add(current)
            next_page = redirects.get(current)
            current = next_page.redirect_url if next_page else None

        if is_loop:
            issues.append(
                DetectedIssue(issue_type="redirect-loop", page_url=url, details={"hops": hops})
            )
        elif len(hops) > 2:
            # url -> a -> b: doua redirecturi inainte de continut = lant
            issues.append(
                DetectedIssue(
                    issue_type="redirect-chain",
                    page_url=url,
                    details={"hops": hops, "final_url": hops[-1]},
                )
            )

    # Ciclurile fara cap (fiecare membru e si tinta - ex. a<->b, sau a->a) nu
    # sunt niciodata atinse pornind dintr-un cap; emitem o bucla per ciclu.
    for url in redirects:
        if url in walked:
            continue
        cycle: list[str] = []
        node = url
        while node and node not in walked:
            walked.add(node)
            cycle.append(node)
            next_page = redirects.get(node)
            node = next_page.redirect_url if next_page and next_page.redirect_url else ""
        issues.append(
            DetectedIssue(issue_type="redirect-loop", page_url=url, details={"hops": [*cycle, url]})
        )

    return issues


def find_broken_internal_links(pages: list[CrawledPage]) -> list[DetectedIssue]:
    """Linkuri interne catre pagini pe care le-am crawlat si le-am vazut esuand.

    Tintele ``blocked``/``rate_limited``/``error`` sunt excluse deliberat: nu
    stim daca linkul e rupt sau doar noi n-am avut acces.
    """
    failing = {
        page.url: page.status_code
        for page in pages
        if page.fetch_class == "ok" and page.status_code >= 400
    }
    if not failing:
        return []

    issues: list[DetectedIssue] = []
    for page in sorted(pages, key=lambda item: item.url):
        for link in sorted(page.links, key=lambda item: item.target_url):
            if not link.is_internal:
                continue
            target_status = failing.get(link.target_url)
            if target_status is None:
                continue
            issues.append(
                DetectedIssue(
                    issue_type="broken-internal-link",
                    page_url=page.url,
                    dedupe_key=link.target_url,
                    details={"target_url": link.target_url, "target_status": target_status},
                )
            )
            if len(issues) >= _BROKEN_LINK_ISSUE_CAP:
                return issues
    return issues


def find_orphan_pages(
    pages: list[CrawledPage], start_url: str, *, crawl_completed: bool
) -> list[DetectedIssue]:
    """Pagini vii (2xx) catre care nu trimite nicio alta pagina crawlata.

    Un auto-link nu salveaza pagina, iar o pagina catre care redirecteaza ceva
    nu e orfana. Pe un crawl trunchiat nu raportam nimic - vezi docstring-ul
    modulului.
    """
    if not crawl_completed:
        return []

    inbound: set[str] = set()
    for page in pages:
        for link in page.links:
            if link.target_url != page.url:
                inbound.add(link.target_url)
        if page.redirect_url:
            inbound.add(page.redirect_url)

    return [
        DetectedIssue(issue_type="orphan-page", page_url=page.url)
        for page in pages
        if _is_ok_html_page(page) and page.url != start_url and page.url not in inbound
    ]


def run_multipage_checks(
    pages: list[CrawledPage], start_url: str, *, crawl_completed: bool
) -> list[DetectedIssue]:
    """Toate verificarile intre pagini, intr-un singur apel."""
    return [
        *find_duplicates(pages),
        *find_redirect_chains_and_loops(pages),
        *find_broken_internal_links(pages),
        *find_orphan_pages(pages, start_url, crawl_completed=crawl_completed),
    ]
