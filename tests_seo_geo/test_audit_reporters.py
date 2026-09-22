"""Verificarile per pagina, SEO si GEO.

Fiecare test schimba UN lucru fata de pagina sanatoasa din ``make_page`` si
verifica exact ce problema apare - asa se vede ca pragul e cel documentat si ca
nu se declanseaza nimic pe langa.
"""

from __future__ import annotations

from seo_geo_agent.audit.geo_reporters import brand_token_from_url, run_geo_page_reporters
from seo_geo_agent.audit.page_analyzer import StructuredData
from seo_geo_agent.audit.page_reporters import run_page_reporters
from tests_seo_geo.conftest import make_page


def _types(page_kwargs: dict[str, object]) -> set[str]:
    return {issue.issue_type for issue in run_page_reporters(make_page(**page_kwargs))}


def _geo_types(page_kwargs: dict[str, object], brand: str = "exemplu") -> set[str]:
    return {issue.issue_type for issue in run_geo_page_reporters(make_page(**page_kwargs), brand)}


def test_pagina_sanatoasa_nu_produce_nicio_problema() -> None:
    assert run_page_reporters(make_page()) == []


def test_pagina_blocata_se_raporteaza_ca_atare_si_se_opreste_acolo() -> None:
    """Un challenge anti-bot nu inseamna ca pagina n-are titlu - inseamna ca n-am vazut-o."""
    assert _types({"fetch_class": "blocked", "status_code": 403}) == {"blocked-page"}


def test_eroarea_de_server_opreste_verificarile_de_continut() -> None:
    assert _types({"status_code": 503}) == {"server-error"}


def test_praguri_de_titlu() -> None:
    assert "missing-title" in _types({"title": ""})
    assert "title-too-long" in _types({"title": "x" * 61})
    assert "title-too-short" in _types({"title": "x" * 9})
    assert not {"title-too-long", "title-too-short"} & _types({"title": "x" * 60})


def test_praguri_de_meta_description() -> None:
    assert "missing-meta-description" in _types({"meta_description": ""})
    assert "meta-description-too-long" in _types({"meta_description": "x" * 161})
    assert "meta-description-too-short" in _types({"meta_description": "x" * 69})


def test_h1_lipsa_sau_multiplu() -> None:
    assert "missing-h1" in _types({"h1_count": 0})
    assert "multiple-h1" in _types({"h1_count": 2})


def test_saritura_de_nivel_in_titluri() -> None:
    assert "heading-order-skip" in _types({"heading_order": [1, 2, 4]})
    assert "heading-order-skip" not in _types({"heading_order": [1, 2, 3, 2]})


def test_continut_subtire_sub_o_suta_cincizeci_de_cuvinte() -> None:
    assert "thin-content" in _types({"word_count": 149})
    assert "thin-content" not in _types({"word_count": 150})


def test_pagina_pe_noindex_nu_mai_e_judecata_pentru_continut() -> None:
    """noindex e de multe ori intentionat; nu adaugam "thin-content" peste el."""
    types = _types({"is_indexable": False, "word_count": 10})
    assert "noindex-page" in types
    assert "thin-content" not in types


def test_canonical_contradictoriu() -> None:
    types = _types(
        {
            "canonical_url": "https://exemplu.ro/a",
            "header_canonical_url": "https://exemplu.ro/b",
        }
    )
    assert "canonical-conflict" in types


def test_raspuns_lent_peste_o_mie_cinci_sute_de_milisecunde() -> None:
    assert "slow-response" in _types({"response_time_ms": 1501})
    assert "slow-response" not in _types({"response_time_ms": 1500})


def test_pagina_adanca_de_la_al_cincilea_click() -> None:
    assert "deep-page" in _types({"crawl_depth": 5})
    assert "deep-page" not in _types({"crawl_depth": 4})


def test_imagini_fara_alt() -> None:
    assert "images-missing-alt" in _types({"images_total": 3, "images_missing_alt": 1})


def test_pagina_fara_niciun_link() -> None:
    assert "no-outgoing-links" in _types({"links": []})


# --- GEO -------------------------------------------------------------------


def test_brandul_se_deduce_din_domeniu() -> None:
    assert brand_token_from_url("https://www.ac-media.ro/servicii") == "ac media"


def test_pagina_geo_sanatoasa_nu_produce_nicio_problema() -> None:
    page = make_page(
        body_text="Exemplu face asta. " * 30 + "Exemplu explica. " * 30,
        word_count=500,
        headings=[(2, "Cum functioneaza Exemplu?")],
        meta_author="Ana Pop",
    )
    assert run_geo_page_reporters(page, "exemplu") == []


def test_html_mare_fara_text_inseamna_randare_in_browser() -> None:
    """Crawler-ele AI nu ruleaza JavaScript: pagina asta e invizibila pentru ele."""
    assert _geo_types({"html_bytes": 200_000, "word_count": 10}) == {
        "content-requires-javascript"
    }


def test_lipsa_json_ld_se_raporteaza() -> None:
    assert "missing-structured-data" in _geo_types({"structured_data": StructuredData()})


def test_brandul_mentionat_de_prea_putine_ori() -> None:
    assert "low-entity-salience" in _geo_types({"body_text": "Noi facem lucruri. " * 100})
    assert "low-entity-salience" not in _geo_types(
        {"body_text": "Exemplu face lucruri. " * 100}
    )


def test_subtitlurile_intrebare_sting_problema() -> None:
    assert "no-answerable-headings" in _geo_types({"headings": [(2, "Serviciile noastre")]})
    assert "no-answerable-headings" not in _geo_types({"headings": [(2, "Cat costa?")]})


def test_propozitii_prea_lungi_pentru_extragere() -> None:
    lung = " ".join(["cuvant"] * 40) + ". "
    assert "long-passages" in _geo_types({"body_text": lung * 6, "word_count": 400})
    scurt = " ".join(["cuvant"] * 12) + ". "
    assert "long-passages" not in _geo_types({"body_text": scurt * 6, "word_count": 400})


def test_paginile_scurte_nu_sunt_judecate_pentru_citabilitate() -> None:
    """Sub 300 de cuvinte, pagina nu e una de continut - verificarile GEO nu se aplica."""
    types = _geo_types({"word_count": 299, "headings": [(2, "Servicii")], "body_text": "x"})
    assert types == set()
