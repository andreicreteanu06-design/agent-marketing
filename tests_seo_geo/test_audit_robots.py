"""Parsarea robots.txt.

Exista pentru ca biblioteca standard NU acopera wildcard-urile ``*``/``$`` si
nici alegerea grupului dupa cel mai specific user-agent - adica exact lucrurile
de care depind crawl-ul si verificarea GEO ``ai-crawler-blocked``.
"""

from __future__ import annotations

from seo_geo_agent.audit.robots import parse_robots_txt

_ROBOTS = """
# comentariu ignorat
User-agent: *
Disallow: /admin/
Disallow: /*?sort=
Allow: /admin/public/

User-agent: GPTBot
Disallow: /

Sitemap: https://exemplu.ro/sitemap.xml
Sitemap: https://exemplu.ro/sitemap-blog.xml
"""


def test_robots_lipsa_permite_tot() -> None:
    robots = parse_robots_txt(None)
    assert robots.fetched is False
    assert robots.is_allowed("https://exemplu.ro/orice", "SeoGeoAgent-Audit/1.0") is True


def test_grupul_generic_se_aplica_unui_agent_necunoscut() -> None:
    robots = parse_robots_txt(_ROBOTS)
    assert robots.is_allowed("https://exemplu.ro/", "SeoGeoAgent-Audit/1.0") is True
    assert robots.is_allowed("https://exemplu.ro/admin/x", "SeoGeoAgent-Audit/1.0") is False


def test_allow_mai_specific_bate_disallow() -> None:
    """Regula lui Google: castiga tiparul cel mai lung, la egalitate castiga Allow."""
    robots = parse_robots_txt(_ROBOTS)
    assert robots.is_allowed("https://exemplu.ro/admin/public/x", "SeoGeoAgent-Audit/1.0") is True


def test_wildcard_prinde_parametrii_din_query() -> None:
    robots = parse_robots_txt(_ROBOTS)
    assert robots.is_allowed("https://exemplu.ro/lista?sort=pret", "SeoGeoAgent-Audit/1.0") is False


def test_grupul_nominal_bate_grupul_generic() -> None:
    """GPTBot e blocat integral desi ``*`` are voie - cazul pe care il raporteaza GEO."""
    robots = parse_robots_txt(_ROBOTS)
    assert robots.blocks_any_path_for("GPTBot") is True
    assert robots.blocks_any_path_for("ClaudeBot") is False


def test_disallow_gol_inseamna_permite_tot() -> None:
    robots = parse_robots_txt("User-agent: *\nDisallow:\n")
    assert robots.is_allowed("https://exemplu.ro/orice", "oricine") is True


def test_sitemap_urile_sunt_colectate() -> None:
    assert parse_robots_txt(_ROBOTS).sitemaps == [
        "https://exemplu.ro/sitemap.xml",
        "https://exemplu.ro/sitemap-blog.xml",
    ]
