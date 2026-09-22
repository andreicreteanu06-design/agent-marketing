"""Tipurile partajate ale motorului de audit.

Portare a ``src/server/lib/audit/types.ts`` din ``every-app/open-seo``.
``CrawledPage`` e forma canonica a unei pagini descarcate: tot ce vine dupa ea
(verificari per pagina, verificari intre pagini, scoruri) lucreaza EXCLUSIV pe
campurile de aici, niciodata pe HTML brut. De asta verificarile sunt functii
pure si testabile fara retea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from seo_geo_agent.audit.page_analyzer import PageLink, StructuredData

#: Cum s-a rezolvat descarcarea paginii. "blocked" = WAF/provocare anti-bot;
#: "rate_limited" = un 429 a impiedicat citirea paginii.
PageFetchClass = Literal["ok", "blocked", "rate_limited", "error"]

#: Numele sub care se prezinta crawler-ul. Apare in explicatiile problemelor
#: "blocked-page"/"rate-limited-page" (utilizatorul il pune pe lista alba).
CRAWL_USER_AGENT = "SeoGeoAgent-Audit/1.0"


@dataclass(slots=True)
class CrawledPage:
    """Rezultatul complet al descarcarii si analizei unei pagini."""

    url: str
    status_code: int
    fetch_class: PageFetchClass
    redirect_url: str | None = None
    title: str = ""
    meta_description: str = ""
    canonical_url: str | None = None
    robots_meta: str | None = None
    x_robots_tag: str | None = None
    header_canonical_url: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    meta_author: str | None = None
    h1_count: int = 0
    heading_order: list[int] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    word_count: int = 0
    body_text: str = ""
    content_hash: str | None = None
    #: ``True`` doar cand s-a descarcat SI analizat un document HTML. Separa
    #: verificarile de continut: un PDF nu are cum sa-i lipseasca tagul title,
    #: o pagina HTML goala foarte mult.
    is_html: bool = False
    #: Octetii de HTML cititi (plafonati). Alimenteaza verificarea GEO
    #: "content-requires-javascript": HTML mare + text aproape zero.
    html_bytes: int = 0
    images_total: int = 0
    images_missing_alt: int = 0
    links: list[PageLink] = field(default_factory=list)
    structured_data: StructuredData = field(default_factory=StructuredData)
    hreflang_tags: list[str] = field(default_factory=list)
    is_indexable: bool = True
    response_time_ms: int = 0
    #: ``None`` = nu s-a ajuns aici prin linkuri (ex. venita din sitemap).
    crawl_depth: int | None = None
    in_sitemap: bool = False
