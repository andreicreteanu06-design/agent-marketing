"""Politica de acces a crawler-ului: ce URL-uri au voie sa fie descarcate.

Portare a ``src/server/lib/audit/url-policy.ts`` din ``every-app/open-seo``.
Scopul e unul singur si serios: SSRF. Endpoint-ul de audit primeste un domeniu
de la un client autentificat si face cereri HTTP catre el de pe serverul nostru
- fara filtrul asta, cineva ar putea tinti ``http://169.254.169.254/`` (metadata
cloud) sau un serviciu intern si ar primi raspunsul inapoi prin raport.

Diferenta fata de original: acolo verificarea intervalelor private e scrisa de
mana (nu exista ``ipaddress`` in Workers). Aici o adresa e acceptata doar daca
``ipaddress`` o considera globala (``is_global``) - asta exclude privatele,
loopback, link-local (deci metadata cloud ``169.254.169.254``), CGNAT
``100.64.0.0/10``, benchmark, rezervatele - plus multicast si IPv4 ascuns in
IPv6 (mapat ``::ffff:a.b.c.d`` sau NAT64 ``64:ff9b::/96``).

Verificarile de aici sunt filtrul RAPID (fara retea) pentru URL-uri. Garantia
vine din ``safe_transport.SafeAsyncTransport``: rezolva DNS-ul la fiecare
cerere, refuza orice adresa interna sau un DNS picat si se conecteaza la IP-ul
verificat - deci nici redirecturile, nici DNS rebinding, nici ``www.<domeniu>``
nu o pot ocoli.
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


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def is_public_address(value: str) -> bool:
    """``True`` doar pentru un IP public, pe care avem voie sa-l atingem.

    Un IPv4 ascuns intr-un IPv6 (mapat sau NAT64) se judeca dupa IPv4-ul lui:
    ``::ffff:10.0.0.1`` ajunge tot in ``10.0.0.1``.
    """
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            _normalize_host(value)
        )
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address in _NAT64:
            address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.is_global and not address.is_multicast


def is_ip_literal(host: str) -> bool:
    """``True`` cand ``host`` e scris ca IP (nu ca nume de domeniu)."""
    try:
        ipaddress.ip_address(_normalize_host(host))
    except ValueError:
        return False
    return True


def _is_blocked_address(host: str) -> bool:
    """``True`` pentru un IP scris literal care nu e public."""
    return is_ip_literal(host) and not is_public_address(host)


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
    if not host or is_ip_literal(host):
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
