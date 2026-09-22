"""Extragerea datelor SEO dintr-o pagina HTML.

Portare a ``src/server/lib/audit/page-analyzer.ts`` din ``every-app/open-seo``,
inclusiv decizia lui centrala: NU construim un DOM. Originalul a inlocuit
cheerio cu tokenizer-ul din ``htmlparser2`` fiindca un DOM complet costa de 5-10
ori dimensiunea HTML-ului per pagina si era principala cauza de OOM la 25 de
pagini analizate simultan. Echivalentul din biblioteca standard Python e
``html.parser.HTMLParser`` - tot un tokenizer in flux, zero dependinte noi.

Trei campuri exista aici si nu in original, toate cerute de verificarile GEO
(``geo_reporters.py``) si toate extrase din acelasi parcurs, fara alt cost:
``headings`` (textul H2/H3, pentru detectia titlurilor-intrebare),
``structured_data`` (tipurile @type din JSON-LD, nu doar "exista/nu exista") si
``meta_author``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from seo_geo_agent.audit.url_utils import is_same_origin, normalize_url

_SKIPPED_LINK_PROTOCOLS = re.compile(r"^(javascript:|mailto:|tel:|#)", re.I)
#: Subarbori al caror text nu e continut vizibil.
_NON_CONTENT_TAGS = frozenset({"script", "style", "noscript", "svg"})
_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
#: Elemente la marginea carora textul se separa. Singura abatere de la
#: original: acolo, nodurile de text se lipesc pur si simplu, deci pe un HTML
#: minificat (fara spatii intre taguri - iesirea obisnuita a unui build modern)
#: ``</h1><p>`` da "TitluText" si numarul de cuvinte iese fals de mic, ceea ce
#: declanseaza "thin-content" pe pagini perfect normale. Separatorul se pune
#: doar la granite de bloc, deci ``<b>Hello</b>world`` ramane un singur cuvant.
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "details", "dialog", "div",
        "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "option", "p", "pre",
        "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)
_MAX_ANCHOR_CHARS = 200
#: Plafoane per pagina. Paginile-capcana si meniurile uriase pot avea mii de
#: linkuri/imagini, iar paginile crawlate stau in memorie cat dureaza auditul.
_MAX_EXTRACTED_LINKS = 1_000
_MAX_EXTRACTED_IMAGES = 1_000
_MAX_HEADINGS = 200
_MAX_JSON_LD_BYTES = 200_000

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class PageLink:
    """O muchie de link iesita din pagina, deduplicata dupa URL-ul tinta."""

    target_url: str
    anchor: str | None
    is_internal: bool
    is_nofollow: bool


@dataclass(slots=True)
class StructuredData:
    """Ce am aflat din blocurile JSON-LD ale paginii."""

    present: bool = False
    types: list[str] = field(default_factory=list)
    has_author: bool = False
    has_date: bool = False


@dataclass(slots=True)
class PageAnalysis:
    """Datele extrase dintr-o singura pagina HTML."""

    url: str
    title: str = ""
    meta_description: str = ""
    canonical: str | None = None
    robots_meta: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    meta_author: str | None = None
    h1s: list[str] = field(default_factory=list)
    heading_order: list[int] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    word_count: int = 0
    body_text: str = ""
    images: list[tuple[str | None, str | None]] = field(default_factory=list)
    links: list[PageLink] = field(default_factory=list)
    structured_data: StructuredData = field(default_factory=StructuredData)
    hreflang_tags: list[str] = field(default_factory=list)


def _collect_json_ld_types(payload: object, into: StructuredData) -> None:
    """Aduna recursiv ``@type``-urile si semnalele de autor/data dintr-un JSON-LD.

    JSON-LD accepta un obiect, o lista sau un ``@graph`` cu mai multe entitati -
    toate trei apar in salbaticie, deci le acceptam pe toate.
    """
    if isinstance(payload, list):
        for item in payload:
            _collect_json_ld_types(item, into)
        return
    if not isinstance(payload, dict):
        return

    raw_type = payload.get("@type")
    if isinstance(raw_type, str):
        into.types.append(raw_type)
    elif isinstance(raw_type, list):
        into.types.extend(item for item in raw_type if isinstance(item, str))

    if payload.get("author"):
        into.has_author = True
    if payload.get("datePublished") or payload.get("dateModified"):
        into.has_date = True

    for key in ("@graph", "mainEntity", "mainEntityOfPage", "hasPart", "itemListElement"):
        if key in payload:
            _collect_json_ld_types(payload[key], into)


class _PageParser(HTMLParser):
    """Tokenizer-ul propriu-zis. Un singur parcurs, o singura trecere peste text."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._page_url = page_url
        self.result = PageAnalysis(url=page_url)

        self._title_depth = 0
        self._title_done = False
        self._title_parts: list[str] = []
        self._saw_title = False
        # ``<noscript>`` e tratat ca text brut cand scripting-ul e activ (asa il
        # vede si un browser): nu extragem elemente din interiorul lui.
        self._noscript_depth = 0
        self._suppress_depth = 0
        self._body_depth = 0
        self._head_depth = 0
        self._saw_body = False
        self._body_parts: list[str] = []
        self._fallback_parts: list[str] = []

        self._open_heading: tuple[int, list[str]] | None = None
        self._open_anchor: tuple[str, str, list[str]] | None = None
        self._links: dict[str, PageLink] = {}
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []
        self._json_ld_bytes = 0

    # -- helpers ---------------------------------------------------------
    def _handle_meta(self, attrs: dict[str, str]) -> None:
        content = attrs.get("content")
        name = (attrs.get("name") or "").lower()
        prop = (attrs.get("property") or "").lower()
        if name == "description" and not self.result.meta_description:
            self.result.meta_description = (content or "").strip()
        elif name == "robots" and self.result.robots_meta is None:
            self.result.robots_meta = content
        elif name == "author" and self.result.meta_author is None:
            self.result.meta_author = content
        elif prop in ("article:published_time", "article:modified_time") and content:
            # Nu e autor, dar e acelasi semnal de prospetime pe care il cauta
            # verificarea GEO; il tratam ca metadata editoriala prezenta.
            self.result.structured_data.has_date = True
        elif prop == "og:title" and self.result.og_title is None:
            self.result.og_title = content
        elif prop == "og:description" and self.result.og_description is None:
            self.result.og_description = content
        elif prop == "og:image" and self.result.og_image is None:
            self.result.og_image = content

    def _handle_link(self, attrs: dict[str, str]) -> None:
        rel = (attrs.get("rel") or "").lower()
        if rel == "canonical" and self.result.canonical is None:
            self.result.canonical = attrs.get("href")
        elif rel == "alternate" and attrs.get("hreflang"):
            self.result.hreflang_tags.append(attrs["hreflang"])

    def _close_anchor(self) -> None:
        if self._open_anchor is None:
            return
        href, rel, text_parts = self._open_anchor
        self._open_anchor = None
        if len(self._links) >= _MAX_EXTRACTED_LINKS:
            return
        resolved = normalize_url(href, self._page_url)
        if resolved is None or resolved in self._links:
            return
        anchor = _WHITESPACE_RE.sub(" ", "".join(text_parts)).strip()[:_MAX_ANCHOR_CHARS]
        self._links[resolved] = PageLink(
            target_url=resolved,
            anchor=anchor or None,
            is_internal=is_same_origin(resolved, self._page_url),
            is_nofollow="nofollow" in rel.split(),
        )

    def _push_block_separator(self) -> None:
        """Marcheaza o granita de bloc in textul vizibil (vezi ``_BLOCK_TAGS``)."""
        if self._suppress_depth > 0 or self._title_depth > 0:
            return
        if self._body_depth > 0:
            self._body_parts.append(" ")
        elif self._head_depth == 0:
            self._fallback_parts.append(" ")

    def _close_heading(self, level: int) -> None:
        if self._open_heading is None or self._open_heading[0] != level:
            return
        text = _WHITESPACE_RE.sub(" ", "".join(self._open_heading[1])).strip()
        self._open_heading = None
        if level == 1:
            self.result.h1s.append(text)
        if len(self.result.headings) < _MAX_HEADINGS:
            self.result.headings.append((level, text))

    # -- callback-urile HTMLParser ---------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _NON_CONTENT_TAGS:
            self._suppress_depth += 1
        if tag == "noscript":
            self._noscript_depth += 1
        if self._noscript_depth > 0:
            return

        attributes = {name: (value if value is not None else "") for name, value in attrs}

        if tag == "title":
            # Un <title> din interiorul unui <svg> nu e titlul documentului.
            if not self._title_done and self._suppress_depth == 0:
                self._title_depth += 1
                self._saw_title = True
        elif tag == "head":
            self._head_depth += 1
        elif tag == "body":
            self._body_depth += 1
            self._saw_body = True
        elif tag == "meta":
            self._handle_meta(attributes)
        elif tag == "link":
            self._handle_link(attributes)
        elif tag == "img":
            if len(self.result.images) < _MAX_EXTRACTED_IMAGES:
                alt = next((value for name, value in attrs if name == "alt"), None)
                has_alt = any(name == "alt" for name, _ in attrs)
                self.result.images.append(
                    (attributes.get("src"), (alt or "") if has_alt else None)
                )
        elif tag == "script":
            if (attributes.get("type") or "").lower() == "application/ld+json":
                self.result.structured_data.present = True
                self._in_json_ld = True
                self._json_ld_parts = []
        elif tag == "a":
            # HTML interzice <a> imbricate; browserele il inchid implicit pe cel
            # deschis, iar tokenizer-ul nu corecteaza arborele - facem la fel.
            self._close_anchor()
            href = attributes.get("href")
            if href and not _SKIPPED_LINK_PROTOCOLS.match(href):
                self._open_anchor = (href, (attributes.get("rel") or "").lower(), [])

        if tag in _BLOCK_TAGS:
            self._push_block_separator()

        level = _HEADING_LEVELS.get(tag)
        if level is not None:
            self.result.heading_order.append(level)
            if self._open_heading is not None:  # titlu neinchis: il inchidem noi
                self._close_heading(self._open_heading[0])
            self._open_heading = (level, [])

    def handle_endtag(self, tag: str) -> None:
        if tag in _NON_CONTENT_TAGS and self._suppress_depth > 0:
            self._suppress_depth -= 1
        if tag == "noscript":
            if self._noscript_depth > 0:
                self._noscript_depth -= 1
            return
        if self._noscript_depth > 0:
            return

        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            try:
                payload = json.loads("".join(self._json_ld_parts))
            except (ValueError, RecursionError):
                payload = None
            if payload is not None:
                _collect_json_ld_types(payload, self.result.structured_data)
            self._json_ld_parts = []
        if tag == "title" and self._title_depth > 0:
            self._title_depth -= 1
            if self._title_depth == 0:
                self._title_done = True
        if tag == "head" and self._head_depth > 0:
            self._head_depth -= 1
        if tag == "body" and self._body_depth > 0:
            self._body_depth -= 1
        if tag == "a":
            self._close_anchor()
        level = _HEADING_LEVELS.get(tag)
        if level is not None:
            self._close_heading(level)
        if tag in _BLOCK_TAGS:
            self._push_block_separator()

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            if self._json_ld_bytes < _MAX_JSON_LD_BYTES:
                self._json_ld_parts.append(data)
                self._json_ld_bytes += len(data)
            return
        if self._suppress_depth > 0:
            return
        if self._title_depth > 0:
            self._title_parts.append(data)
            return
        if self._open_heading is not None:
            self._open_heading[1].append(data)
        if self._open_anchor is not None:
            self._open_anchor[2].append(data)
        if self._body_depth > 0:
            self._body_parts.append(data)
        elif self._head_depth == 0:
            self._fallback_parts.append(data)

    def finish(self) -> PageAnalysis:
        """Inchide elementele ramase deschise si calculeaza textul/numarul de cuvinte."""
        self._close_anchor()
        if self._open_heading is not None:
            self._close_heading(self._open_heading[0])

        # Textul vizibil: preferam ce e in <body>; documentele fara <body>
        # (fragmente) cad pe tot textul din afara lui <head>.
        raw_text = "".join(self._body_parts if self._saw_body else self._fallback_parts)
        body_text = _WHITESPACE_RE.sub(" ", raw_text).strip()

        self.result.title = "".join(self._title_parts).strip() if self._saw_title else ""
        self.result.body_text = body_text
        self.result.word_count = len(body_text.split()) if body_text else 0
        self.result.links = list(self._links.values())
        return self.result


def analyze_html(html: str, page_url: str) -> PageAnalysis:
    """Analizeaza ``html`` si intoarce datele SEO/GEO extrase.

    Nu ridica exceptii pentru HTML stricat: ``HTMLParser`` tolereaza taguri
    neinchise sau imbricate gresit, exact ca un browser, iar pe noi ne
    intereseaza ce ar vedea un crawler real, nu daca documentul e valid.
    """
    parser = _PageParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.finish()
