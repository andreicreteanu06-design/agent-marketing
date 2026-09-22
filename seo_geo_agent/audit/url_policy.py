"""Politica de acces a crawler-ului: ce URL-uri au voie sa fie descarcate.

Portare a ``src/server/lib/audit/url-policy.ts`` din ``every-app/open-seo``.
Scopul e unul singur si serios: SSRF. Endpoint-ul de audit primeste un domeniu
de la un client autentificat si face cereri HTTP catre el de pe serverul nostru
- fara filtrul asta, cineva ar putea tinti ``http://169.254.169.254/`` (metadata
cloud) sau un serviciu intern si ar primi raspunsul inapoi prin raport.

Diferenta fata de original: acolo verificarea intervalelor private e scrisa de
mana (nu exista ``ipaddress`` in Workers). Aici folosim ``ipaddress`` din
biblioteca standard, care acopera aceleasi intervale si inca cateva (CGNAT,
benchmark, rezervate) - mai strict, nu mai permisiv.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from seo_geo_agent.audit.url_utils import normalize_url

_BLOCKED_HOSTS = frozenset(
    {"localhost", "metadata.google.internal", "metadata", "169.254.169.254", "100.100.100.200"}
)
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa")

_DNS_TIMEOUT_SECONDS = 2.5


class CrawlTargetBlockedError(Exception):
    """Tinta ceruta e un host intern/privat - nu o atingem, indiferent cine cere."""


def _normalize_host(hostname: str) -> str:
    host = hostname.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "%" in host:  # zona IPv6 ("fe80::1%eth0")
        host = host.split("%", 1)[0]
    return host.removesuffix(".")


def _is_blocked_address(host: str) -> bool:
    """``True`` pentru orice IP pe care nu avem voie sa-l atingem."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def is_blocked_host(hostname: str) -> bool:
    """Verificare sincrona, fara retea: nume interne si IP-uri private/loopback."""
    host = _normalize_host(hostname)
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    if host.endswith(_BLOCKED_HOST_SUFFIXES):
        return True
    return _is_blocked_address(host)


def is_crawlable_url(url: str) -> bool:
    """Verificare sincrona pentru URL-urile descoperite in timpul crawl-ului.

    Blocheaza schemele care nu sunt http(s), IP-urile private/loopback scrise
    literal si numele interne. Rezolvarea DNS se face DOAR pentru URL-ul de
    start (vezi :func:`normalize_and_validate_start_url`): un lookup pentru
    fiecare link descoperit ar fi prohibitiv de lent.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https"):
        return False
    return not is_blocked_host(parts.hostname or "")


async def _resolves_to_blocked_address(hostname: str) -> bool:
    """``True`` daca vreo adresa in care se rezolva ``hostname`` e privata/interna.

    Asta prinde cazul in care un domeniu public (``intern.exemplu.ro``) are un
    A record catre ``10.0.0.5``. Esecul lookup-ului nu blocheaza: cererea
    ulterioara va esua oricum, iar un DNS temporar mort nu trebuie sa arate ca
    un refuz de securitate.
    """
    host = _normalize_host(hostname)
    if not host or _is_ip_literal(host):
        return False
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP), timeout=_DNS_TIMEOUT_SECONDS
        )
    except (TimeoutError, OSError):
        return False
    return any(_is_blocked_address(_normalize_host(str(info[4][0]))) for info in infos)


async def normalize_and_validate_start_url(raw: str) -> str:
    """Normalizeaza URL-ul de start si refuza tintele interne.

    Acepta si un domeniu gol (``exemplu.ro``) - se completeaza cu ``https://``,
    la fel ca in original.

    Raises:
        ValueError: intrare goala sau URL care nu se poate parsa ca http(s).
        CrawlTargetBlockedError: host intern, IP privat, sau nume care se
            rezolva intr-o adresa privata.
    """
    value = raw.strip()
    if not value:
        raise ValueError("URL gol")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"

    normalized = normalize_url(value)
    if normalized is None:
        raise ValueError("URL invalid")

    hostname = urlsplit(normalized).hostname or ""
    if is_blocked_host(hostname):
        raise CrawlTargetBlockedError(hostname)
    if await _resolves_to_blocked_address(hostname):
        raise CrawlTargetBlockedError(hostname)
    return normalized
