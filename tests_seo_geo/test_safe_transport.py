"""Scutul SSRF: transportul care se conecteaza doar la IP-uri publice verificate.

Fara retea si fara DNS real: rezolvarea e o functie falsa, iar transportul real
e un ``httpx.MockTransport``. Invariantul central e negativ - nicio cerere catre
o adresa interna nu ajunge la transportul real, oricum ar fi ascunsa (nume care
se rezolva intern, redirect, ``www.`` al unui domeniu public, DNS picat).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from seo_geo_agent.audit.safe_transport import SafeAsyncTransport, SsrfBlockedError
from seo_geo_agent.audit.service import AuditConfig, run_audit

PUBLIC_IP = "93.184.216.34"


class _Dns:
    """Rezolvare falsa: nume -> adrese; tine minte ce s-a intrebat."""

    def __init__(self, records: dict[str, list[str]], *, error: Exception | None = None) -> None:
        self.records = records
        self.error = error
        self.asked: list[str] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.asked.append(host)
        if self.error is not None:
            raise self.error
        return self.records.get(host, [])


class _Upstream:
    """Transportul real, simulat: tine minte cererile care AU ajuns la el."""

    def __init__(self, respond: object = None) -> None:
        self.seen: list[httpx.Request] = []
        self.created = 0
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if callable(self._respond):
            return self._respond(request)  # type: ignore[no-any-return]
        return httpx.Response(200, html="<html><title>ok</title></html>")

    def factory(self) -> httpx.AsyncBaseTransport:
        self.created += 1
        return httpx.MockTransport(self)


def _get(url: str, transport: SafeAsyncTransport, **kwargs: object) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, **kwargs) as client:  # type: ignore[arg-type]
            return await client.get(url)

    return asyncio.run(_run())


def _shield(dns: _Dns, upstream: _Upstream) -> SafeAsyncTransport:
    return SafeAsyncTransport(resolver=dns, transport_factory=upstream.factory)


# --- drumul bun: conexiune la IP-ul verificat, nu la nume ------------------------


def test_a_public_host_is_pinned_to_the_verified_ip() -> None:
    dns = _Dns({"exemplu.ro": [PUBLIC_IP]})
    upstream = _Upstream()

    response = _get("https://exemplu.ro/servicii?x=1", _shield(dns, upstream))

    [sent] = upstream.seen
    assert sent.url == httpx.URL(f"https://{PUBLIC_IP}/servicii?x=1")
    assert sent.headers["host"] == "exemplu.ro"  # site-ul primeste numele lui
    assert sent.extensions["sni_hostname"] == "exemplu.ro"  # TLS verifica numele
    assert response.url == httpx.URL("https://exemplu.ro/servicii?x=1")  # apelantul vede numele


def test_a_public_ip_literal_needs_no_dns_and_no_sni() -> None:
    dns = _Dns({})
    upstream = _Upstream()

    _get(f"http://{PUBLIC_IP}/", _shield(dns, upstream))

    assert dns.asked == []
    [sent] = upstream.seen
    assert "sni_hostname" not in sent.extensions


# --- ce se refuza ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "internal",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",  # metadata cloud
        "100.64.0.1",  # CGNAT - retele interne k8s / Tailscale
        "192.168.1.10",
        "::1",
        "::ffff:127.0.0.1",  # IPv4 ascuns in IPv6
        "fd00::1",
        "0.0.0.0",
    ],
)
def test_a_name_that_resolves_internally_never_reaches_the_network(internal: str) -> None:
    dns = _Dns({"intern.exemplu.ro": [internal]})
    upstream = _Upstream()

    with pytest.raises(SsrfBlockedError, match="adresa interna"):
        _get("https://intern.exemplu.ro/", _shield(dns, upstream))
    assert upstream.seen == []


def test_one_internal_address_among_public_ones_is_enough_to_refuse() -> None:
    dns = _Dns({"mixt.ro": [PUBLIC_IP, "10.0.0.5"]})
    upstream = _Upstream()

    with pytest.raises(SsrfBlockedError):
        _get("https://mixt.ro/", _shield(dns, upstream))
    assert upstream.seen == []


@pytest.mark.parametrize("error", [OSError("NXDOMAIN"), TimeoutError()])
def test_a_failed_dns_lookup_is_refused_not_retried_blindly(error: Exception) -> None:
    upstream = _Upstream()

    with pytest.raises(SsrfBlockedError, match="DNS nu a rezolvat"):
        _get("https://exemplu.ro/", _shield(_Dns({}, error=error), upstream))
    assert upstream.seen == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/",
    ],
)
def test_internal_targets_are_refused_before_any_dns_lookup(url: str) -> None:
    dns = _Dns({})
    upstream = _Upstream()

    with pytest.raises(SsrfBlockedError):
        _get(url, _shield(dns, upstream))
    assert dns.asked == []
    assert upstream.seen == []


def test_a_redirect_to_an_internal_name_is_refused_mid_chain() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://rebind.exemplu.ro/secret"})

    dns = _Dns({"exemplu.ro": [PUBLIC_IP], "rebind.exemplu.ro": ["10.0.0.5"]})
    upstream = _Upstream(respond)

    with pytest.raises(SsrfBlockedError, match=r"10.0.0.5"):
        _get("https://exemplu.ro/", _shield(dns, upstream), follow_redirects=True)
    assert [request.headers["host"] for request in upstream.seen] == ["exemplu.ro"]


def test_each_host_gets_its_own_connection_pool() -> None:
    dns = _Dns({"a.ro": [PUBLIC_IP], "b.ro": [PUBLIC_IP]})
    upstream = _Upstream()
    shield = _shield(dns, upstream)

    async def _run() -> None:
        async with httpx.AsyncClient(transport=shield) as client:
            await client.get("https://a.ro/")
            await client.get("https://a.ro/2")
            await client.get("https://b.ro/")

    asyncio.run(_run())
    assert upstream.created == 2  # un TLS validat pentru a.ro nu e refolosit pentru b.ro


# --- auditul SEO: bypass-ul prin www. ---------------------------------------------------


def test_the_audit_cannot_be_walked_into_the_internal_network_through_www() -> None:
    """attacker.ro e public si trece validarea; www.attacker.ro (aceeasi "origine"
    pentru crawler) se rezolva in 10.0.0.5. Inainte, auditul il descarca."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "attacker.ro":
            return httpx.Response(301, headers={"location": "https://www.attacker.ro/"})
        return httpx.Response(200, html="<html><title>panou intern</title></html>")

    dns = _Dns({"attacker.ro": [PUBLIC_IP], "www.attacker.ro": ["10.0.0.5"]})
    upstream = _Upstream(respond)
    shield = SafeAsyncTransport(resolver=dns, transport_factory=upstream.factory)

    result = asyncio.run(
        run_audit(
            "https://attacker.ro/",
            AuditConfig(max_pages=5, time_budget_seconds=10),
            transport=shield,
        )
    )

    assert {request.headers["host"] for request in upstream.seen} == {"attacker.ro"}
    assert all("panou intern" not in (page.title or "") for page in result.pages)
