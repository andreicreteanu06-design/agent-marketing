"""Extragerea datelor SEO din HTML.

Verificam doar lucrurile in care un tokenizer poate gresi si in care greseala
schimba raportul: ce e text vizibil, ce e titlu, cum se numara imaginile fara
alt si cum se deduplica linkurile.
"""

from __future__ import annotations

from seo_geo_agent.audit.page_analyzer import analyze_html

_URL = "https://exemplu.ro/pagina"


def test_extrage_metadatele_din_head() -> None:
    html = """
    <html><head>
      <title>  Titlu cu spatii  </title>
      <meta name="description" content="Descrierea paginii">
      <meta name="robots" content="noindex, follow">
      <meta property="og:image" content="/og.png">
      <link rel="canonical" href="/pagina">
      <link rel="alternate" hreflang="en" href="/en/page">
    </head><body><h1>H</h1></body></html>
    """
    result = analyze_html(html, _URL)
    assert result.title == "Titlu cu spatii"
    assert result.meta_description == "Descrierea paginii"
    assert result.robots_meta == "noindex, follow"
    assert result.og_image == "/og.png"
    assert result.canonical == "/pagina"
    assert result.hreflang_tags == ["en"]


def test_titlul_din_svg_nu_e_titlul_documentului() -> None:
    """Capcana din original: <svg><title> ar fura titlul paginii."""
    html = "<html><head><svg><title>iconita</title></svg></head><body>x</body></html>"
    assert analyze_html(html, _URL).title == ""


def test_scriptul_si_stilul_nu_sunt_text_vizibil() -> None:
    html = """
    <html><body>
      <p>Vizibil</p>
      <script>var ascuns = "nu se vede";</script>
      <style>.x { color: red }</style>
    </body></html>
    """
    result = analyze_html(html, _URL)
    assert result.body_text == "Vizibil"
    assert result.word_count == 1


def test_html_minificat_pastreaza_granitele_dintre_blocuri() -> None:
    """Fara separator, ``</h1><p>`` ar da un singur cuvant si "thin-content" fals."""
    result = analyze_html("<html><body><h1>Unu</h1><p>Doi trei</p></body></html>", _URL)
    assert result.body_text == "Unu Doi trei"
    assert result.word_count == 3


def test_alt_gol_nu_e_alt_lipsa() -> None:
    """alt="" e marcajul CORECT pentru o imagine decorativa - nu se raporteaza."""
    html = '<html><body><img src="a.png" alt=""><img src="b.png"></body></html>'
    images = analyze_html(html, _URL).images
    assert images == [("a.png", ""), ("b.png", None)]


def test_linkurile_se_deduplica_si_se_clasifica() -> None:
    html = """
    <html><body>
      <a href="/a">Unu</a>
      <a href="/a">Duplicat, ignorat</a>
      <a href="https://altul.ro/b" rel="nofollow">Extern</a>
      <a href="mailto:x@y.ro">Email, ignorat</a>
      <a href="#sus">Ancora, ignorata</a>
    </body></html>
    """
    links = analyze_html(html, _URL).links
    assert [(link.target_url, link.is_internal, link.is_nofollow) for link in links] == [
        ("https://exemplu.ro/a", True, False),
        ("https://altul.ro/b", False, True),
    ]


def test_json_ld_da_tipurile_si_semnalele_de_autor() -> None:
    html = """
    <html><head><script type="application/ld+json">
      {"@context":"https://schema.org","@graph":[
        {"@type":"Organization","name":"Exemplu"},
        {"@type":"Article","author":{"name":"Ana"},"datePublished":"2026-01-01"}]}
    </script></head><body>x</body></html>
    """
    data = analyze_html(html, _URL).structured_data
    assert data.present is True
    assert sorted(data.types) == ["Article", "Organization"]
    assert data.has_author is True
    assert data.has_date is True


def test_json_ld_invalid_nu_arunca() -> None:
    """Un JSON-LD stricat exista pe site-uri reale; auditul nu are voie sa cada."""
    html = (
        '<html><head><script type="application/ld+json">{nu e json}</script></head>'
        "<body>x</body></html>"
    )
    data = analyze_html(html, _URL).structured_data
    assert data.present is True
    assert data.types == []
