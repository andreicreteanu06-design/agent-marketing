"""Crawler-ul live al agentului PPC, construit peste motorul de audit SEO/GEO.

Fara retea reala: totul prin ``httpx.MockTransport``. Invariantul central e
negativ - o pagina pe care site-ul ne-a oprit-o NU trebuie sa ajunga in raport
ca pagina goala.
"""

from __future__ import annotations

import httpx
import pytest

from ppc_agent.errors import (
    CrawlBlockedError,
    CrawlError,
    CrawlTargetBlockedError,
    CrawlTimeoutError,
)
from ppc_agent.ingestion.crawler import crawl
from ppc_agent.providers.live.crawler import LiveCrawlerProvider

_PAGE = "https://exemplu.ro/servicii"
_HTML = "<html><head><title>Service auto</title></head><body><h1>Service auto</h1></body></html>"


def _provider(handler: object) -> LiveCrawlerProvider:
    return LiveCrawlerProvider(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_paginile_bune_vin_cu_html_brut() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "SeoGeoAgent-Audit/1.0"
        return httpx.Response(200, html=_HTML)

    result = _provider(handler).fetch(_PAGE)
    assert result.ok is True
    assert result.status_code == 200
    assert "Service auto" in result.html
    assert result.final_url == _PAGE


def test_redirectul_ajunge_la_url_ul_final() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/servicii":
            return httpx.Response(301, headers={"Location": "https://exemplu.ro/service-auto"})
        return httpx.Response(200, html=_HTML)

    result = _provider(handler).fetch(_PAGE)
    assert result.ok is True
    assert result.final_url == "https://exemplu.ro/service-auto"


@pytest.mark.parametrize("status", [403, 429])
def test_cand_site_ul_ne_opreste_nu_raportam_pagina_goala(status: int) -> None:
    """Deosebirea dintre "n-are continut" si "n-am avut voie sa citesc"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, html="<html><body>nope</body></html>")

    with pytest.raises(CrawlBlockedError):
        _provider(handler).fetch(_PAGE)


def test_challenge_ul_anti_bot_e_blocare_nu_continut() -> None:
    """Un 503 cu pagina de challenge Cloudflare nu e pagina clientului.

    Pragul e cel din ``classify_fetch``: markerii de corp se verifica pe 503,
    iar un challenge servit cu 200 se recunoaste dupa antetul ``cf-mitigated``.
    Nu adaugam aici o a doua euristica - ar insemna doua politici de
    clasificare in acelasi repo, exact ce evita modulul asta.
    """

    def challenge_503(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, html="<html><title>Just a moment...</title></html>")

    with pytest.raises(CrawlBlockedError):
        _provider(challenge_503).fetch(_PAGE)

    def mitigated_200(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=_HTML, headers={"cf-mitigated": "challenge"})

    with pytest.raises(CrawlBlockedError):
        _provider(mitigated_200).fetch(_PAGE)


def test_timeoutul_are_tipul_lui() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("prea lent")

    with pytest.raises(CrawlTimeoutError):
        _provider(handler).fetch(_PAGE)


def test_esecul_de_retea_ramane_crawl_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    with pytest.raises(CrawlError):
        _provider(handler).fetch(_PAGE)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/admin",
        "file:///etc/passwd",
        "http://localhost/",
    ],
)
def test_tintele_interzise_nu_produc_nicio_cerere(url: str) -> None:
    """URL-ul unei pagini de destinatie vine din datele clientului - nu e de incredere."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    with pytest.raises(CrawlTargetBlockedError):
        _provider(handler).fetch(url)


def test_un_document_non_html_nu_e_continut_utilizabil() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
        )

    result = _provider(handler).fetch(_PAGE)
    assert result.ok is False
    assert result.html == ""


def test_404_ul_nu_e_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, html="<html><body>nu exista</body></html>")

    result = _provider(handler).fetch(_PAGE)
    assert result.ok is False
    assert result.status_code == 404


# --- robots.txt -------------------------------------------------------------


def test_robots_txt_se_citeste_de_la_radacina() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://exemplu.ro/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")

    text = _provider(handler).robots_txt("https://exemplu.ro")
    assert text is not None
    assert "Disallow: /admin" in text


def test_robots_txt_lipsa_inseamna_nu_stiu_nu_interdictie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert _provider(handler).robots_txt("https://exemplu.ro") is None


def test_un_robots_txt_inaccesibil_nu_opreste_analiza() -> None:
    """Fara asta, o retea capricioasa ar bloca tot Modulul 1 pentru un fisier optional."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    assert _provider(handler).robots_txt("https://exemplu.ro") is None


# --- integrarea cu Modulul 1 ------------------------------------------------


def test_modulul_1_produce_un_page_context_real() -> None:
    """Capatul lantului: providerul + parsarea existenta, fara mock in mijloc."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            html=(
                "<html><head><title>Service auto Bucuresti</title>"
                '<meta name="description" content="Reparatii rapide."></head>'
                "<body><h1>Service auto Bucuresti</h1><h2>Program</h2>"
                '<a href="/contact">Cere o oferta</a></body></html>'
            ),
        )

    context = crawl(_provider(handler), _PAGE)
    assert context.ok is True
    assert context.title == "Service auto Bucuresti"
    assert context.h1 == ["Service auto Bucuresti"]
    assert "Cere o oferta" in context.cta_texts


def test_robots_txt_care_interzice_opreste_crawl_ul() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /servicii\n")
        raise AssertionError("pagina nu ar trebui ceruta")

    context = crawl(_provider(handler), _PAGE)
    assert context.ok is False
    assert context.failure_reason == "blocat_de_robots_txt"


def test_motivul_blocarii_ajunge_in_page_context() -> None:
    """``failure_reason`` trebuie sa distinga blocarea de o pagina goala."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(403, html="<html><body>forbidden</body></html>")

    context = crawl(_provider(handler), _PAGE)
    assert context.ok is False
    assert context.failure_reason == "CrawlBlockedError"
