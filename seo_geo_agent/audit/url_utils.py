"""Normalizare si comparare de URL-uri pentru crawler.

Portare a ``src/server/lib/audit/url-utils.ts`` din ``every-app/open-seo``,
inclusiv comentariile care explica DE CE o regula e asa (ele sunt partea
valoroasa - fiecare e o capcana pe care originalul a calcat-o deja).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _build_netloc(scheme: str, hostname: str, port: str | None) -> str:
    """Reasambleaza ``host[:port]``, fara portul implicit al schemei (ca ``URL`` din JS)."""
    if port and port != _DEFAULT_PORTS.get(scheme):
        return f"{hostname}:{port}"
    return hostname


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Normalizeaza un URL pentru deduplicare.

    - rezolva URL-urile relative fata de ``base``
    - elimina fragmentul (``#...``)
    - sorteaza parametrii din query
    - trece hostname-ul la litere mici
    - PASTREAZA slash-ul final. Pe majoritatea CMS-urilor (WordPress etc.)
      forma canonica e cea cu slash, iar varianta fara el da 301 catre ea.
      Daca l-am taia aici, am rescrie URL-ul canonic in propria lui sursa de
      redirect, iar crawler-ul ar urma ``/path`` -> ``/path/`` -> ``/path``
      la nesfarsit (bucla 508). Tinandu-le distincte, redirectul se rezolva normal.

    Returneaza ``None`` pentru orice nu e http(s) sau nu se poate parsa.
    """
    try:
        absolute = urljoin(base, url) if base else url
        parts = urlsplit(absolute)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if not parts.hostname:
        return None

    try:
        port = str(parts.port) if parts.port is not None else None
    except ValueError:
        return None  # port nenumeric ("example.com:abc") - URL invalid, nu-l crawlam

    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True), key=lambda kv: kv[0]))
    netloc = _build_netloc(scheme, parts.hostname.lower(), port)
    return urlunsplit((scheme, netloc, parts.path, query, ""))


def canonical_url_key(url: str) -> str:
    """Cheie de egalitate care supravietuieste redirecturilor uzuale catre forma canonica.

    Forteaza https, taie ``www.`` de la inceput, trece hostname-ul la litere
    mici, sorteaza query-ul si elimina fragmentul. Slash-ul final ramane intact,
    ca doua cai chiar diferite sa nu se suprapuna niciodata; cheia asta e doar
    pentru intrebarea "e practic aceeasi pagina ca URL-ul de start?" (ex.
    alegerea paginii principale), nu pentru deduplicarea din crawl.
    """
    normalized = normalize_url(url)
    if normalized is None:
        return url.lower()
    parts = urlsplit(normalized)
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return urlunsplit(("https", hostname, parts.path, parts.query, ""))


def _equivalent_hostnames(a: str, b: str) -> bool:
    host_a, host_b = a.lower(), b.lower()
    return host_a == host_b or host_a == f"www.{host_b}" or host_b == f"www.{host_a}"


def _effective_port(parts: tuple[str, str | None]) -> str:
    scheme, port = parts
    return port or _DEFAULT_PORTS.get(scheme, "")


def is_same_origin(url: str, origin: str) -> bool:
    """Spune daca ``url`` e in aceeasi granita de crawl ca ``origin``.

    Reguli:
    - hostname-ul trebuie sa coincida (cu/fara ``www.`` conteaza ca acelasi)
    - acelasi protocol+port e mereu permis
    - upgrade-ul http -> https pe porturile implicite e permis
    """
    try:
        parsed_url = urlsplit(url)
        parsed_origin = urlsplit(origin)
        url_host, origin_host = parsed_url.hostname, parsed_origin.hostname
        if not url_host or not origin_host:
            return False
        if not _equivalent_hostnames(url_host, origin_host):
            return False
        url_scheme = parsed_url.scheme.lower()
        origin_scheme = parsed_origin.scheme.lower()
        url_port = _effective_port((url_scheme, str(parsed_url.port) if parsed_url.port else None))
        origin_port = _effective_port(
            (origin_scheme, str(parsed_origin.port) if parsed_origin.port else None)
        )
    except ValueError:
        return False

    if url_scheme == origin_scheme:
        return url_port == origin_port
    return (
        origin_scheme == "http"
        and url_scheme == "https"
        and origin_port == "80"
        and url_port == "443"
    )


def get_origin(url: str) -> str:
    """``scheme://host[:port]`` pentru ``url`` (fara cale, query sau fragment)."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port = str(parts.port) if parts.port is not None else None
    netloc = _build_netloc(scheme, (parts.hostname or "").lower(), port)
    return urlunsplit((scheme, netloc, "", "", ""))


def detect_url_template(pathname: str) -> str:
    """Inlocuieste segmentele care arata a valori dinamice cu un parametru.

    ``/blog/articolul-meu-grozav`` -> ``/blog/:slug``;
    ``/produse/12345`` -> ``/produse/:id``.
    Grupeaza paginile generate din acelasi sablon in rapoarte.
    """
    normalized: list[str] = []
    for segment in (part for part in pathname.split("/") if part):
        if segment.isdigit():
            normalized.append(":id")
        elif _UUID_RE.match(segment):
            normalized.append(":uuid")
        elif _DATE_RE.match(segment):
            normalized.append(":date")
        elif "-" in segment and len(segment.split("-")) > 2:
            # Slug: contine cratime si are peste 2 bucati, ca sa nu prindem rute
            # fixe scurte ("contul-meu").
            normalized.append(":slug")
        else:
            normalized.append(segment)
    return "/" + "/".join(normalized)
