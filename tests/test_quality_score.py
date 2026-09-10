"""Teste pentru optimizatorul de Quality Score."""

from __future__ import annotations

from ppc_agent.alignment.models import AdGroupInput
from ppc_agent.alignment.quality_score import _tfidf_cosine, analyze_ad_group
from ppc_agent.ingestion.models import PageContext


def _page(h1: list[str], h2: list[str] | None = None) -> PageContext:
    return PageContext(
        url="https://exemplu.ro",
        ok=True,
        status_code=200,
        title="Exemplu",
        h1=h1,
        h2=h2 or [],
        cta_texts=["Cere o oferta", "Incepe gratuit"],
    )


def test_fully_aligned_group_scores_high_on_all_components() -> None:
    page = _page(
        h1=["Servicii curatenie birouri Bucuresti"],
        h2=["Preturi servicii curatenie", "De ce noi"],
    )
    ad_group = AdGroupInput(
        ad_group_id="ag1",
        name="Curatenie birouri",
        exact_match_keyword="servicii curatenie birouri",
        headlines=[
            "Servicii curatenie birouri Bucuresti",
            "Curatenie birouri rapida - cere o oferta",
        ],
        descriptions=["Cere o oferta pentru servicii curatenie birouri."],
    )
    report = analyze_ad_group(ad_group, page)

    assert report.expected_ctr == "High"
    assert report.ad_relevance == "High"
    assert report.landing_page_experience == "High"
    assert report.score >= 8.0
    assert not report.flagged


def test_keyword_missing_from_h1_forces_landing_low_with_suggestion() -> None:
    page = _page(h1=["Bine ati venit pe site"], h2=["Despre noi"])
    ad_group = AdGroupInput(
        ad_group_id="ag2",
        name="Contabilitate",
        exact_match_keyword="servicii contabilitate",
        headlines=["Servicii contabilitate pentru firme"],
        descriptions=["Contactati-ne."],
    )
    report = analyze_ad_group(ad_group, page)

    assert report.landing_page_experience == "Low"
    assert any("H1 nu contine" in suggestion for suggestion in report.suggestions)
    assert not report.keyword_in_h1


def test_flag_set_when_keyword_absent_from_h1_and_headlines() -> None:
    page = _page(h1=["Pagina noastra"])
    ad_group = AdGroupInput(
        ad_group_id="ag3",
        name="Fara aliniere",
        exact_match_keyword="transport marfa international",
        headlines=["Cea mai buna oferta", "Suna acum"],
        descriptions=["Servicii premium."],
    )
    report = analyze_ad_group(ad_group, page)

    assert report.flagged
    assert not report.keyword_in_h1
    assert not report.keyword_in_headlines
    assert report.landing_page_experience == "Low"


def test_keyword_in_headlines_but_not_h1_is_not_flagged() -> None:
    page = _page(h1=["Bine ati venit"])
    ad_group = AdGroupInput(
        ad_group_id="ag4",
        name="Partial",
        exact_match_keyword="reparatii frigidere",
        headlines=["Reparatii frigidere la domiciliu"],
        descriptions=["Interventie rapida."],
    )
    report = analyze_ad_group(ad_group, page)

    assert not report.flagged
    assert report.keyword_in_headlines
    assert report.landing_page_experience == "Low"  # tot Low: lipseste din H1


def test_tfidf_cosine_identical_and_disjoint() -> None:
    assert _tfidf_cosine("servicii curatenie birouri", "servicii curatenie birouri") == 1.0
    assert _tfidf_cosine("mere pere caise", "tramvai autobuz metrou") == 0.0
    assert _tfidf_cosine("", "orice text") == 0.0


def test_report_is_deterministic() -> None:
    page = _page(h1=["Servicii SEO Bucuresti"])
    ad_group = AdGroupInput(
        ad_group_id="ag5",
        name="SEO",
        exact_match_keyword="servicii seo",
        headlines=["Servicii SEO care aduc trafic"],
        descriptions=["Audit gratuit."],
    )
    first = analyze_ad_group(ad_group, page)
    second = analyze_ad_group(ad_group, page)
    assert first.model_dump() == second.model_dump()


def test_components_recorded_in_report() -> None:
    page = _page(h1=["Cursuri de germana online"])
    ad_group = AdGroupInput(
        ad_group_id="ag6",
        name="Germana",
        exact_match_keyword="cursuri germana online",
        headlines=["Cursuri de germana online cu profesori nativi"],
        descriptions=["Incepe azi."],
    )
    report = analyze_ad_group(ad_group, page)
    assert set(report.components) == {
        "keyword_headline_coverage",
        "keyword_landing_coverage",
        "headline_h1_similarity",
        "description_cta_alignment",
    }
    assert report.components["keyword_headline_coverage"] == 1.0
