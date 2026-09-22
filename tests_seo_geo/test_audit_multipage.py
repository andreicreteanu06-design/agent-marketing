"""Verificarile intre pagini: duplicate, redirecturi, linkuri rupte, orfane.

Aici stau regulile care fac diferenta intre un raport corect si unul care sperie
degeaba - fiecare test tine una dintre ele.
"""

from __future__ import annotations

from seo_geo_agent.audit.multipage import (
    find_broken_internal_links,
    find_duplicates,
    find_orphan_pages,
    find_redirect_chains_and_loops,
)
from seo_geo_agent.audit.page_analyzer import PageLink
from seo_geo_agent.audit.types import CrawledPage
from tests_seo_geo.conftest import make_page


def _link(target: str) -> PageLink:
    return PageLink(target_url=target, anchor=None, is_internal=True, is_nofollow=False)


def _redirect(url: str, target: str) -> CrawledPage:
    return CrawledPage(url=url, status_code=301, fetch_class="ok", redirect_url=target)


def test_titlurile_identice_raporteaza_fiecare_pagina_din_grup() -> None:
    pages = [
        make_page("https://exemplu.ro/a", title="Acelasi titlu peste tot"),
        make_page("https://exemplu.ro/b", title="Acelasi titlu peste tot"),
        make_page("https://exemplu.ro/c", title="Un titlu diferit si unic"),
    ]
    issues = [i for i in find_duplicates(pages) if i.issue_type == "duplicate-title"]
    assert {issue.page_url for issue in issues} == {
        "https://exemplu.ro/a",
        "https://exemplu.ro/b",
    }
    assert issues[0].details["group_size"] == 2


def test_paginile_deja_canonicalizate_nu_intra_in_duplicate() -> None:
    """Proprietarul a rezolvat deja problema; a i-o raporta ar fi zgomot."""
    pages = [
        make_page("https://exemplu.ro/a", title="Acelasi"),
        make_page(
            "https://exemplu.ro/b", title="Acelasi", canonical_url="https://exemplu.ro/a"
        ),
    ]
    assert [i for i in find_duplicates(pages) if i.issue_type == "duplicate-title"] == []


def test_lantul_de_redirecturi_da_o_singura_problema_pe_cap_de_lant() -> None:
    pages = [
        _redirect("https://exemplu.ro/a", "https://exemplu.ro/b"),
        _redirect("https://exemplu.ro/b", "https://exemplu.ro/c"),
        make_page("https://exemplu.ro/c"),
    ]
    issues = find_redirect_chains_and_loops(pages)
    assert len(issues) == 1
    assert issues[0].issue_type == "redirect-chain"
    assert issues[0].page_url == "https://exemplu.ro/a"
    assert issues[0].details["final_url"] == "https://exemplu.ro/c"


def test_bucla_fara_cap_e_tot_detectata() -> None:
    """a -> b -> a: fiecare e si tinta, deci nu exista cap de lant din care sa pornim."""
    pages = [
        _redirect("https://exemplu.ro/a", "https://exemplu.ro/b"),
        _redirect("https://exemplu.ro/b", "https://exemplu.ro/a"),
    ]
    issues = find_redirect_chains_and_loops(pages)
    assert [issue.issue_type for issue in issues] == ["redirect-loop"]


def test_un_singur_redirect_nu_e_problema() -> None:
    pages = [
        _redirect("https://exemplu.ro/a", "https://exemplu.ro/b"),
        make_page("https://exemplu.ro/b"),
    ]
    assert find_redirect_chains_and_loops(pages) == []


def test_linkul_rupt_se_raporteaza_pe_pagina_sursa() -> None:
    pages = [
        make_page("https://exemplu.ro/a", links=[_link("https://exemplu.ro/lipsa")]),
        CrawledPage(url="https://exemplu.ro/lipsa", status_code=404, fetch_class="ok"),
    ]
    issues = find_broken_internal_links(pages)
    assert len(issues) == 1
    assert issues[0].page_url == "https://exemplu.ro/a"
    assert issues[0].details == {"target_url": "https://exemplu.ro/lipsa", "target_status": 404}


def test_tinta_blocata_nu_inseamna_link_rupt() -> None:
    """Un 403 de la un WAF nu e dovada ca linkul e rupt - doar ca noi n-am avut acces."""
    pages = [
        make_page("https://exemplu.ro/a", links=[_link("https://exemplu.ro/x")]),
        CrawledPage(url="https://exemplu.ro/x", status_code=403, fetch_class="blocked"),
    ]
    assert find_broken_internal_links(pages) == []


def test_pagina_orfana_e_cea_catre_care_nu_trimite_nimeni() -> None:
    pages = [
        make_page("https://exemplu.ro/", links=[_link("https://exemplu.ro/a")]),
        make_page("https://exemplu.ro/a", links=[]),
        make_page("https://exemplu.ro/orfana", links=[]),
    ]
    issues = find_orphan_pages(pages, "https://exemplu.ro/", crawl_completed=True)
    assert [issue.page_url for issue in issues] == ["https://exemplu.ro/orfana"]


def test_pe_crawl_trunchiat_nu_se_raporteaza_orfane() -> None:
    """Fara graf complet, "nimeni nu linkuieste aici" e date lipsa, nu dovada."""
    pages = [make_page("https://exemplu.ro/orfana", links=[])]
    assert find_orphan_pages(pages, "https://exemplu.ro/", crawl_completed=False) == []
