"""Scorurile SEO/GEO.

Invariantele pe care se bazeaza increderea in numarul afisat: un site fara
probleme ia 100, un site complet cazut ia 0, iar problemele pe care originalul
le numeste intentionate nu scad scorul.
"""

from __future__ import annotations

from seo_geo_agent.audit.page_reporters import DetectedIssue, run_page_reporters
from seo_geo_agent.audit.scoring import compute_pillar_scores
from seo_geo_agent.audit.types import CrawledPage
from tests_seo_geo.conftest import make_page


def test_site_fara_probleme_ia_suta() -> None:
    pages = [make_page("https://exemplu.ro/")]
    assert compute_pillar_scores(pages, [])["seo"].score == 100


def test_site_complet_cazut_ia_zero() -> None:
    """5xx peste tot deschide doar slotul de disponibilitate - si il pica peste tot."""
    pages = [
        CrawledPage(url=f"https://exemplu.ro/{i}", status_code=500, fetch_class="ok")
        for i in range(5)
    ]
    issues = [issue for page in pages for issue in run_page_reporters(page)]
    assert compute_pillar_scores(pages, issues)["seo"].score == 0


def test_noindex_intentionat_nu_scade_scorul() -> None:
    """Originalul spune explicit "often intentional"; nu pedepsim o configurare corecta."""
    page = make_page("https://exemplu.ro/multumim", is_indexable=False)
    issues = run_page_reporters(page)
    assert {issue.issue_type for issue in issues} == {"noindex-page"}
    assert compute_pillar_scores([page], issues)["seo"].score == 100


def test_o_problema_scade_scorul_proportional_cu_greutatea_ei() -> None:
    pages = [make_page("https://exemplu.ro/")]
    critic = compute_pillar_scores(pages, [DetectedIssue("missing-title", pages[0].url)])
    informativ = compute_pillar_scores(pages, [DetectedIssue("title-too-long", pages[0].url)])
    assert critic["seo"].score < informativ["seo"].score < 100


def test_doua_probleme_in_acelasi_slot_pica_slotul_o_singura_data() -> None:
    pages = [make_page("https://exemplu.ro/")]
    una = compute_pillar_scores(pages, [DetectedIssue("missing-h1", pages[0].url)])
    doua = compute_pillar_scores(
        pages,
        [DetectedIssue("missing-h1", pages[0].url), DetectedIssue("multiple-h1", pages[0].url)],
    )
    assert una["seo"].score == doua["seo"].score


def test_problemele_de_site_scad_doar_scorul_geo() -> None:
    pages = [make_page("https://exemplu.ro/")]
    scores = compute_pillar_scores(
        pages, [DetectedIssue("ai-crawler-blocked", "https://exemplu.ro/")]
    )
    assert scores["seo"].score == 100
    assert scores["geo"].score < 100
