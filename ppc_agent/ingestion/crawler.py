"""Crawler de domeniu: transforma o pagina intr-un :class:`PageContext` tipizat.

Mecanismul de descarcare (Playwright / httpx) traieste in furnizorul de crawling.
Acest modul contine logica de *parsare* — partea care merita testata — si o
functie de orchestrare care aplica politica ``robots.txt``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from ppc_agent.errors import CrawlError
from ppc_agent.ingestion.models import PageContext
from ppc_agent.ingestion.robots import RobotsPolicy
from ppc_agent.providers.base import CrawlerProvider

USER_AGENT = "ppc-agent-crawler"

_CTA_HINTS: tuple[str, ...] = (
    "cumpara",
    "comanda",
    "adauga in cos",
    "solicita",
    "cere oferta",
    "cere o oferta",
    "incepe",
    "inscrie",
    "aboneaza",
    "contacteaza",
    "programeaza",
    "descarca",
    "get started",
    "buy now",
    "sign up",
    "book a demo",
    "request a quote",
    "try free",
    "start now",
)
_MAX_CTA_LEN = 40


def _tag_text(node: Tag) -> str:
    """Textul vizibil al unui element, cu spatiile normalizate."""
    return node.get_text(" ", strip=True)


def _all_tags(soup: BeautifulSoup, name: str) -> list[Tag]:
    """Toate elementele ``name`` din document, filtrate strict la :class:`Tag`."""
    return [node for node in soup.find_all(name) if isinstance(node, Tag)]


def _dedupe(values: list[str]) -> list[str]:
    """Elimina duplicatele pastrand ordinea de aparitie."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _meta_description(soup: BeautifulSoup) -> str:
    node = soup.find("meta", attrs={"name": "description"})
    if not isinstance(node, Tag):
        return ""
    content = node.get("content", "")
    return content.strip() if isinstance(content, str) else ""


def _cta_texts(soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    for node in [*_all_tags(soup, "button"), *_all_tags(soup, "a")]:
        label = _tag_text(node)
        if not label or len(label) > _MAX_CTA_LEN:
            continue
        lowered = label.casefold()
        if any(hint in lowered for hint in _CTA_HINTS):
            found.append(label)
    return _dedupe(found)


def _nav_items(soup: BeautifulSoup) -> list[str]:
    nav = soup.find("nav")
    if not isinstance(nav, Tag):
        return []
    items = [_tag_text(link) for link in nav.find_all("a") if isinstance(link, Tag)]
    return _dedupe([item for item in items if item])


def _usp_candidates(soup: BeautifulSoup, h1: list[str]) -> list[str]:
    """Fraze scurte de propunere de valoare: subtitlu hero / primul paragraf.

    Euristica: primul ``<p>`` semnificativ dupa primul ``<h1>``, plus textul din
    elementele marcate ca ``.hero``, ``.subtitle`` sau ``[data-usp]``.
    """
    candidates: list[str] = []

    first_h1 = soup.find("h1")
    if isinstance(first_h1, Tag):
        sibling = first_h1.find_next("p")
        if isinstance(sibling, Tag):
            text = _tag_text(sibling)
            if 20 <= len(text) <= 200:
                candidates.append(text)

    for selector in (".hero p", ".subtitle", "[data-usp]"):
        for node in soup.select(selector):
            text = _tag_text(node)
            if 12 <= len(text) <= 200:
                candidates.append(text)

    return _dedupe([*candidates, *(h for h in h1 if 12 <= len(h) <= 120)])[:5]


def build_page_context(html: str, url: str, status_code: int) -> PageContext:
    """Parseaza HTML-ul unei pagini intr-un :class:`PageContext`.

    Args:
        html: Continutul HTML brut.
        url: URL-ul canonic al paginii.
        status_code: Codul HTTP asociat raspunsului.

    Returns:
        Contextul paginii, cu ``ok=True``.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.find("title")
    title = _tag_text(title_node) if isinstance(title_node, Tag) else ""

    h1 = [_tag_text(node) for node in _all_tags(soup, "h1")]
    h2 = [_tag_text(node) for node in _all_tags(soup, "h2")]
    h3 = [_tag_text(node) for node in _all_tags(soup, "h3")]

    return PageContext(
        url=url,
        ok=True,
        status_code=status_code,
        title=title,
        meta_description=_meta_description(soup),
        h1=[text for text in h1 if text],
        h2=[text for text in h2 if text],
        h3=[text for text in h3 if text],
        cta_texts=_cta_texts(soup),
        nav_items=_nav_items(soup),
        usp_candidates=_usp_candidates(soup, [text for text in h1 if text]),
    )


def base_origin(url: str) -> str:
    """Originea (schema + host) a unui URL, utila pentru ``robots.txt``."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def crawl(provider: CrawlerProvider, url: str, *, user_agent: str = USER_AGENT) -> PageContext:
    """Aplica ``robots.txt``, obtine pagina prin ``provider`` si o parseaza.

    Gestioneaza: pagina blocata de ``robots.txt``, timeout (``CrawlTimeoutError``),
    cod 404 si raspuns fara continut. Toate esecurile produc un ``PageContext`` cu
    ``ok=False`` si un ``failure_reason``.

    Args:
        provider: Furnizorul de crawling (mock sau live).
        url: Pagina de analizat.
        user_agent: Agentul folosit pentru evaluarea ``robots.txt``.

    Returns:
        Contextul paginii.
    """
    policy = RobotsPolicy(provider.robots_txt(base_origin(url)), user_agent)
    if not policy.can_fetch(url):
        return PageContext.failed(url, reason="blocat_de_robots_txt")

    try:
        result = provider.fetch(url)
    except CrawlError as exc:
        return PageContext.failed(url, reason=type(exc).__name__)

    if result.status_code == 404:
        return PageContext.failed(url, status_code=404, reason="not_found")
    if not result.ok or not result.html.strip():
        return PageContext.failed(url, status_code=result.status_code, reason="continut_gol")

    return build_page_context(result.html, result.final_url or url, result.status_code)
