"""Auditul cap-coada, pe un site fals servit de ``httpx.MockTransport``.

Zero retea reala (vezi README). Testul verifica ce nu se poate verifica din
functiile pure: ca descoperirea, crawl-ul, respectarea robots.txt, bugetele si
verificarile se leaga corect intre ele.
"""

from __future__ import annotations

import asyncio

import httpx

from seo_geo_agent.audit.service import AuditConfig, AuditResult, run_audit

_LONG_TEXT = "cuvant " * 200


def _page(title: str, body: str) -> str:
    return (
        f"<html><head><title>{title}</title>"
        '<meta name="description" content="O descriere suficient de lunga incat sa '
        'treaca pragul de saptezeci de caractere cerut de verificare.">'
        f"</head><body><h1>{title}</h1>{body}</body></html>"
    )


_SITE = {
    "/": _page("Pagina principala Exemplu", f"<p>{_LONG_TEXT}</p><a href='/despre'>Despre</a>"),
    "/despre": _page("Despre noi la Exemplu", f"<p>{_LONG_TEXT}</p><a href='/'>Acasa</a>"),
    "/privat": _page("Zona privata", "<p>secret</p>"),
}

_SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://exemplu.ro/</loc></url>"
    "<url><loc>https://exemplu.ro/orfana</loc></url>"
    "</urlset>"
)

_ROBOTS = (
    "User-agent: *\nDisallow: /privat\n"
    "User-agent: GPTBot\nDisallow: /\n"
    "Sitemap: https://exemplu.ro/sitemap.xml\n"
)


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text=_ROBOTS)
    if path == "/llms.txt":
        return httpx.Response(404)
    if path == "/sitemap.xml":
        return httpx.Response(200, headers={"content-type": "application/xml"}, text=_SITEMAP)
    if path == "/orfana":
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_page("Pagina orfana de test", f"<p>{_LONG_TEXT}</p>"),
        )
    body = _SITE.get(path)
    if body is None:
        return httpx.Response(404, headers={"content-type": "text/html"}, text="<html>404</html>")
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def _run(config: AuditConfig | None = None) -> AuditResult:
    return asyncio.run(
        run_audit(
            "https://exemplu.ro/",
            config or AuditConfig(max_pages=10),
            transport=httpx.MockTransport(_handler),
        )
    )


def test_auditul_crawleaza_sitemapul_si_linkurile() -> None:
    result = _run()
    assert {page.url for page in result.pages} == {
        "https://exemplu.ro/",
        "https://exemplu.ro/despre",
        "https://exemplu.ro/orfana",
    }
    assert result.completed is True
    assert result.robots_txt_found is True
    assert result.llms_txt_found is False
    assert result.sitemap_urls_found == 2


def test_robots_txt_e_respectat() -> None:
    """/privat e interzis prin robots.txt - nu apare in raport, desi exista."""
    assert all(page.url != "https://exemplu.ro/privat" for page in _run().pages)


def test_crawlerul_ai_blocat_se_raporteaza_o_singura_data() -> None:
    result = _run()
    blocked = [issue for issue in result.issues if issue.issue_type == "ai-crawler-blocked"]
    assert len(blocked) == 1
    assert any("GPTBot" in name for name in blocked[0].details["blocked_crawlers"])


def test_bugetul_de_pagini_trunchiaza_auditul() -> None:
    """Sub buget, raportul se marcheaza partial si verificarea de orfane nu ruleaza."""
    result = _run(AuditConfig(max_pages=1))
    assert len(result.pages) == 1
    assert result.completed is False
    assert all(issue.issue_type != "orphan-page" for issue in result.issues)


def test_brandul_se_deduce_din_domeniu_cand_nu_e_dat() -> None:
    assert _run().brand == "exemplu"


def test_scorurile_sunt_in_interval_si_reproductibile() -> None:
    first, second = _run(), _run()
    assert 0 <= first.scores["seo"].score <= 100
    assert 0 <= first.scores["geo"].score <= 100
    assert first.scores == second.scores
