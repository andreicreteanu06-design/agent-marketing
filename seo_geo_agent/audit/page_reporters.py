"""Verificarile SEO care se pot face privind o singura pagina.

Portare a ``src/server/lib/audit/issues/page-reporters.ts`` din
``every-app/open-seo``, cu ACELEASI praguri numerice - nu sunt inventate aici,
sunt cele pe care le foloseste originalul:

===========================  =======  ==========================================
prag                         valoare  de ce
===========================  =======  ==========================================
TITLE_MAX_CHARS                   60  peste, rezultatul cautarii taie titlul
TITLE_MIN_CHARS                   10  sub, titlul e prea generic ca sa descrie ceva
META_DESCRIPTION_MAX_CHARS       160  peste, fragmentul din SERP e taiat
META_DESCRIPTION_MIN_CHARS        70  sub, se risipeste spatiul din SERP
THIN_CONTENT_WORDS               150  sub, pagina e "subtire" pentru motoare
SLOW_RESPONSE_MS                1500  peste, TTFB-ul trage in jos tot ce urmeaza
DEEP_PAGE_DEPTH                    5  la 5+ clickuri de acasa, pagina e neglijata
===========================  =======  ==========================================

Fiecare verificare e o functie pura peste ``CrawledPage`` - fara retea, fara
baza de date, fara HTML. Verificarile intre pagini (duplicate, linkuri rupte,
orfane) sunt in ``multipage.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_geo_agent.audit.types import CrawledPage

TITLE_MAX_CHARS = 60
TITLE_MIN_CHARS = 10
META_DESCRIPTION_MAX_CHARS = 160
META_DESCRIPTION_MIN_CHARS = 70
THIN_CONTENT_WORDS = 150
SLOW_RESPONSE_MS = 1500
DEEP_PAGE_DEPTH = 5


@dataclass(slots=True)
class DetectedIssue:
    """O problema gasita, cu dovada ei: URL-ul afectat si valorile masurate."""

    issue_type: str
    page_url: str
    details: dict[str, Any] = field(default_factory=dict)
    #: Distinge mai multe probleme de acelasi tip pe aceeasi pagina (ex. cate un
    #: "broken-internal-link" per tinta rupta).
    dedupe_key: str | None = None


def _has_heading_level_skip(heading_order: list[int]) -> bool:
    """``True`` daca ierarhia sare un nivel (ex. H2 urmat direct de H4)."""
    return any(
        heading_order[i] > heading_order[i - 1] + 1 for i in range(1, len(heading_order))
    )


def run_page_reporters(page: CrawledPage) -> list[DetectedIssue]:
    """Toate problemele SEO vizibile din datele unei singure pagini."""
    issues: list[DetectedIssue] = []

    def report(issue_type: str, **details: Any) -> None:
        issues.append(DetectedIssue(issue_type=issue_type, page_url=page.url, details=details))

    if page.fetch_class == "blocked":
        report("blocked-page", status_code=page.status_code)
        return issues
    if page.fetch_class == "rate_limited":
        report("rate-limited-page", status_code=page.status_code)
        return issues
    if page.fetch_class == "error":
        return issues

    if page.status_code >= 500:
        report("server-error", status_code=page.status_code)
        return issues
    if page.status_code >= 400:
        report("broken-page", status_code=page.status_code)
        return issues
    # Un redirect singur e normal; lanturile si buclele se semnaleaza in multipage.
    if page.status_code >= 300:
        return issues

    if page.response_time_ms > SLOW_RESPONSE_MS:
        report("slow-response", response_time_ms=page.response_time_ms)

    # Verificarile de continut au sens doar pentru documente HTML analizate: un
    # PDF n-are cum sa-i lipseasca tagul title, o pagina HTML goala foarte mult.
    if not page.is_html:
        return issues

    # Titluri
    if not page.title:
        report("missing-title")
    elif len(page.title) > TITLE_MAX_CHARS:
        report("title-too-long", length=len(page.title))
    elif len(page.title) < TITLE_MIN_CHARS:
        report("title-too-short", length=len(page.title))

    # Meta description
    if not page.meta_description:
        report("missing-meta-description")
    elif len(page.meta_description) > META_DESCRIPTION_MAX_CHARS:
        report("meta-description-too-long", length=len(page.meta_description))
    elif len(page.meta_description) < META_DESCRIPTION_MIN_CHARS:
        report("meta-description-too-short", length=len(page.meta_description))

    # Titluri de sectiune
    if page.h1_count == 0:
        report("missing-h1")
    elif page.h1_count > 1:
        report("multiple-h1", h1_count=page.h1_count)
    if _has_heading_level_skip(page.heading_order):
        report("heading-order-skip")

    # Indexabilitate + semnale canonice
    if not page.is_indexable:
        report("noindex-page", robots_meta=page.robots_meta, x_robots_tag=page.x_robots_tag)
    if (
        page.canonical_url
        and page.header_canonical_url
        and page.canonical_url != page.header_canonical_url
    ):
        report(
            "canonical-conflict",
            html_canonical=page.canonical_url,
            header_canonical=page.header_canonical_url,
        )
    effective_canonical = page.canonical_url or page.header_canonical_url
    if effective_canonical and effective_canonical != page.url:
        report("canonicalized-page", canonical_url=effective_canonical)

    # Calitatea continutului
    if page.is_indexable and page.word_count < THIN_CONTENT_WORDS:
        report("thin-content", word_count=page.word_count)
    if page.images_missing_alt > 0:
        report(
            "images-missing-alt",
            images_missing_alt=page.images_missing_alt,
            images_total=page.images_total,
        )

    # Structura
    if page.is_indexable and not page.links:
        report("no-outgoing-links")
    if page.crawl_depth is not None and page.crawl_depth >= DEEP_PAGE_DEPTH:
        report("deep-page", crawl_depth=page.crawl_depth)

    return issues
