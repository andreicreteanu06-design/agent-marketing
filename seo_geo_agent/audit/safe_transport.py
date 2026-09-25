"""Scutul SSRF: un transport ``httpx`` care se conecteaza DOAR la IP-uri publice.

Validarea unui URL inainte de cerere (``url_policy``) nu ajunge: intre
verificare si conexiune, ``httpx`` rezolva numele din nou. Un domeniu poate
raspunde public la verificare si ``10.0.0.5`` la conexiune (DNS rebinding),
poate redirectiona spre un alt nume, iar ``www.<domeniu>`` - acceptat ca
aceeasi origine - nu fusese rezolvat deloc. De aceea verificarea se muta
acolo unde nu se poate ocoli, in transport, la FIECARE cerere (inclusiv
fiecare salt de redirect, fiecare sitemap, fiecare link descoperit):

1. rezolvam noi numele (``getaddrinfo``, cu timeout);
2. daca DNS-ul pica sau ORICARE adresa nu e publica (privata, loopback,
   link-local ``169.254.0.0/16`` - deci si metadata cloud -, CGNAT
   ``100.64.0.0/10``, rezervata, multicast, IPv4 mapat in IPv6), cererea se
   refuza cu :class:`SsrfBlockedError` - fail closed;
3. ne conectam la IP-ul verificat, nu la nume: URL-ul trimis mai departe are
   IP-ul, antetul ``Host`` pastreaza numele, iar TLS verifica certificatul
   pentru nume (extensia ``sni_hostname`` a ``httpcore``). Nu mai exista o a
   doua rezolvare pe care cineva sa o poata otravi.

Raspunsul ramane legat de cererea originala (``httpx`` i-o ataseaza dupa
transport), deci ``response.url``, redirecturile relative si comparatiile de
origine vad in continuare numele, nu IP-ul.

``SsrfBlockedError`` e un ``httpx.ConnectError``: codul care prinde deja erorile
de retea ale crawler-elor il trateaza ca pe o conexiune refuzata, fara cazuri noi.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable

import httpx

from seo_geo_agent.audit.url_policy import is_blocked_host, is_ip_literal, is_public_address

#: Cat asteptam DNS-ul. Peste, cererea se refuza (nu "se incearca oricum").
DNS_TIMEOUT_SECONDS = 2.5

Resolver = Callable[[str, int], Awaitable[list[str]]]
TransportFactory = Callable[[], httpx.AsyncBaseTransport]


class SsrfBlockedError(httpx.ConnectError):
    """Cererea tintea o adresa interna, sau numele nu s-a putut rezolva sigur."""


async def resolve_host(host: str, port: int) -> list[str]:
    """Adresele IP ale lui ``host``, in ordinea data de sistem, fara duplicate."""
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=DNS_TIMEOUT_SECONDS
    )
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class SafeAsyncTransport(httpx.AsyncBaseTransport):
    """Transport ``httpx`` cu scut SSRF - vezi docstring-ul modulului.

    Args:
        limits: Limitele de conexiuni ale transporturilor reale (``httpx``
            ignora ``limits`` pe client cand primeste un ``transport``).
        resolver: Rezolvarea DNS; injectata in teste.
        transport_factory: Transportul real, cate unul per nume de host (o
            conexiune TLS validata pentru un nume nu e refolosita pentru altul
            care se intampla sa aiba acelasi IP); injectat in teste.
    """

    def __init__(
        self,
        *,
        limits: httpx.Limits | None = None,
        resolver: Resolver = resolve_host,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        resolved_limits = limits or httpx.Limits()
        self._resolver = resolver
        self._factory: TransportFactory = transport_factory or (
            lambda: httpx.AsyncHTTPTransport(limits=resolved_limits)
        )
        self._transports: dict[str, httpx.AsyncBaseTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise SsrfBlockedError(f"schema interzisa: {url.scheme}", request=request)
        host = url.host
        if is_blocked_host(host):
            raise SsrfBlockedError(f"host intern interzis: {host}", request=request)

        address = await self._public_address(request, host, url.port)
        extensions = dict(request.extensions)
        if not is_ip_literal(host):
            extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=address),
            headers=request.headers,  # pastreaza ``Host: <nume>``
            stream=request.stream,
            extensions=extensions,
        )
        transport = self._transports.get(host)
        if transport is None:
            transport = self._transports[host] = self._factory()
        return await transport.handle_async_request(pinned)

    async def _public_address(self, request: httpx.Request, host: str, port: int | None) -> str:
        if is_ip_literal(host):
            if not is_public_address(host):
                raise SsrfBlockedError(f"adresa interna interzisa: {host}", request=request)
            return host
        default_port = 443 if request.url.scheme == "https" else 80
        try:
            addresses = await self._resolver(host, port or default_port)
        except (OSError, TimeoutError) as exc:
            raise SsrfBlockedError(
                f"DNS nu a rezolvat '{host}' ({type(exc).__name__}) - cerere refuzata",
                request=request,
            ) from exc
        if not addresses:
            raise SsrfBlockedError(f"'{host}' nu are nicio adresa", request=request)
        internal = [address for address in addresses if not is_public_address(address)]
        if internal:
            raise SsrfBlockedError(
                f"'{host}' se rezolva intr-o adresa interna ({internal[0]}) - cerere refuzata",
                request=request,
            )
        return addresses[0]

    async def aclose(self) -> None:
        transports, self._transports = list(self._transports.values()), {}
        for transport in transports:
            await transport.aclose()
