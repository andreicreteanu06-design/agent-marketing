"""Verificarile pentru afaceri locale si testul de prezenta GEO.

Toate au pornit de la acelasi caz real (un restaurant dintr-un lant cu
francize, noiembrie 2026): pagina locatiei avea doar program si telefon, dar
trecea de "thin-content" datorita meniului repetat; nu declara LocalBusiness,
dar "missing-structured-data" tacea pentru ca pluginul SEO punea WebPage;
telefonul, codul postal si programul difereau intre site, Google si platforma
de livrare; o pagina "Hello world!" era publica; cosul si contul ocupau bugetul
de crawl; iar brandul lipsea din raspunsurile la intrebarile clientilor, desi
auditul ii dadea 93 la GEO.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from seo_geo_agent import router as router_module
from seo_geo_agent.app import create_app
from seo_geo_agent.audit.crawler import page_from_html
from seo_geo_agent.audit.geo_reporters import run_geo_page_reporters
from seo_geo_agent.audit.nap import (
    ReferenceListing,
    find_nap_mismatches,
    hours_ranges_in_text,
    is_location_page,
    normalize_phone,
    phones_in_text,
)
from seo_geo_agent.audit.page_analyzer import analyze_html
from seo_geo_agent.audit.page_reporters import run_page_reporters
from seo_geo_agent.audit.scoring import compute_pillar_scores
from seo_geo_agent.audit.service import AuditConfig, run_audit
from seo_geo_agent.audit.url_utils import is_utility_url
from seo_geo_agent.presence import (
    QuestionPresence,
    SearchHit,
    evaluate_presence,
    evaluate_question,
    probe_presence,
)
from tests_seo_geo.conftest import make_page

_MENU = (
    "<nav>"
    + " ".join(f"<a href='/locatie-{i}'>Locatia numarul {i}</a>" for i in range(40))
    + "</nav>"
)
_FOOTER = "<footer>" + "Politica de confidentialitate Politica cookies ANPC " * 10 + "</footer>"
_LOCATION_BODY = (
    "<h1>Locatia Centru</h1><p>Luni - Vineri de la 10:30 - 22:00</p>"
    "<p><a href='tel:+40773957224'>(0773) 957 224</a></p>"
)


def _location_html(json_ld: str = '{"@type": "WebPage"}') -> str:
    return (
        "<html><head><title>Locatia Centru - Exemplu</title>"
        f'<script type="application/ld+json">{json_ld}</script></head>'
        f"<body>{_MENU}{_LOCATION_BODY}{_FOOTER}</body></html>"
    )


# --- analiza paginii -------------------------------------------------------------


def test_meniul_si_subsolul_nu_intra_in_cuvintele_de_continut() -> None:
    analysis = analyze_html(_location_html(), "https://exemplu.ro/locatie-centru/")
    assert analysis.word_count > 150  # tot textul, ca inainte
    assert analysis.main_word_count < 20  # doar titlul, programul si telefonul


def test_linkurile_tel_si_datele_locale_din_json_ld_se_extrag() -> None:
    json_ld = (
        '{"@type": "Restaurant", "telephone": "+40 773 957 224",'
        ' "address": {"@type": "PostalAddress", "postalCode": "011146"},'
        ' "openingHours": "Mo-Fr 10:30-22:00"}'
    )
    analysis = analyze_html(_location_html(json_ld), "https://exemplu.ro/locatie-centru/")
    assert analysis.phone_links == ["+40773957224"]
    assert analysis.structured_data.telephones == ["+40 773 957 224"]
    assert analysis.structured_data.postal_codes == ["011146"]
    assert analysis.structured_data.has_opening_hours is True
    # tel: nu e un link de crawlat
    assert all(not link.target_url.startswith("tel:") for link in analysis.links)


# --- thin-content si pagini implicite ----------------------------------------------


def test_pagina_goala_cu_meniu_lung_e_subtire() -> None:
    page = page_from_html("https://exemplu.ro/locatie-centru/", 200, _location_html())
    thin = [issue for issue in run_page_reporters(page) if issue.issue_type == "thin-content"]
    assert len(thin) == 1
    assert thin[0].details["word_count"] < 20
    assert thin[0].details["total_word_count"] > 150


def test_paginile_fara_numar_separat_cad_pe_word_count() -> None:
    """Paginile construite in teste vechi (fara main_word_count) se comporta ca inainte."""
    assert "thin-content" not in {i.issue_type for i in run_page_reporters(make_page())}


@pytest.mark.parametrize(
    ("url", "title", "body"),
    [
        ("https://exemplu.ro/hello-world/", "Un titlu oarecare de articol", "text " * 300),
        ("https://exemplu.ro/blog/ceva/", "Hello world! - Exemplu", "text " * 300),
        ("https://exemplu.ro/servicii/", "Servicii Exemplu", "Lorem ipsum dolor sit amet " * 60),
    ],
)
def test_paginile_implicite_ale_cms_ului_se_raporteaza(url: str, title: str, body: str) -> None:
    page = make_page(url, title=title, body_text=body)
    assert "cms-placeholder-page" in {i.issue_type for i in run_page_reporters(page)}


def test_widgetul_recent_posts_nu_face_din_orice_pagina_una_implicita() -> None:
    """Bara laterala a unui blog WordPress lasat asa listeaza "Hello world!" peste tot."""
    page = make_page(
        "https://exemplu.ro/shop/",
        title="Shop - Exemplu",
        body_text="Produse " * 200 + "Recent Posts Hello world! Recent Comments",
    )
    assert "cms-placeholder-page" not in {i.issue_type for i in run_page_reporters(page)}


def test_pagina_implicita_pe_noindex_nu_se_raporteaza() -> None:
    page = make_page("https://exemplu.ro/hello-world/", is_indexable=False)
    assert "cms-placeholder-page" not in {i.issue_type for i in run_page_reporters(page)}


# --- telefon, program, pagina de locatie ---------------------------------------------


@pytest.mark.parametrize(
    "raw", ["0773 957 224", "+40 773 957 224", "0040773957224", "(0773) 957-224", "+40773957224"]
)
def test_telefoanele_romanesti_se_normalizeaza_la_aceeasi_forma(raw: str) -> None:
    assert normalize_phone(raw) == "0773957224"


def test_orele_si_datele_nu_sunt_telefoane() -> None:
    assert phones_in_text("Program 10:30 - 22:00, rezervari pe 2026-11-23, cod 011146") == set()
    assert phones_in_text("Suna la 021 312 45 67 pentru rezervari") == {"0213124567"}


def test_intervalele_orare_se_normalizeaza() -> None:
    assert hours_ranges_in_text("L-V 10.30 - 22:00, S-D 12:30 pana la 22:00") == {
        "10:30-22:00",
        "12:30-22:00",
    }


def test_pagina_de_locatie_cere_telefon_si_program() -> None:
    both = make_page(body_text="Program 10:30-22:00, telefon 0773 957 224")
    phone_only = make_page(body_text="Contact: 0773 957 224 " + "text " * 300)
    assert is_location_page(both) is True
    assert is_location_page(phone_only) is False


def test_pagina_de_locatie_fara_local_business_e_semnalata() -> None:
    page = page_from_html("https://exemplu.ro/locatie-centru/", 200, _location_html())
    issues = {i.issue_type for i in run_geo_page_reporters(page, "exemplu")}
    assert "missing-local-business-schema" in issues
    assert "missing-structured-data" not in issues  # WebPage exista - de asta tacea inainte


def test_pagina_de_locatie_cu_restaurant_nu_e_semnalata() -> None:
    page = page_from_html(
        "https://exemplu.ro/locatie-centru/", 200, _location_html('{"@type": "Restaurant"}')
    )
    issues = {i.issue_type for i in run_geo_page_reporters(page, "exemplu")}
    assert "missing-local-business-schema" not in issues


def test_slotul_local_business_se_deschide_doar_pe_paginile_de_locatie() -> None:
    location = page_from_html("https://exemplu.ro/locatie-centru/", 200, _location_html())
    normal = make_page("https://exemplu.ro/despre/")
    issues = run_geo_page_reporters(location, "exemplu")
    with_location = compute_pillar_scores([location, normal], issues)["geo"]
    without_issue = compute_pillar_scores(
        [location, normal],
        [i for i in issues if i.issue_type != "missing-local-business-schema"],
    )["geo"]
    assert with_location.score < without_issue.score
    only_normal = compute_pillar_scores([normal], [])["geo"]
    assert only_normal.score == 100


# --- NAP fata de listarile externe -----------------------------------------------------


def _nap_page() -> object:
    return page_from_html(
        "https://exemplu.ro/locatie-centru/",
        200,
        _location_html(
            '{"@type": "Restaurant", "address": {"@type": "PostalAddress", "postalCode": "011146"}}'
        ),
    )


def test_listarea_identica_nu_produce_diferente() -> None:
    reference = ReferenceListing(
        source="Google Business Profile",
        phone="+40 773 957 224",
        postal_code="011146",
        hours=("10:30-22:00",),
    )
    assert find_nap_mismatches([_nap_page()], [reference], site_url="https://exemplu.ro/") == []


def test_diferentele_de_telefon_cod_si_program_se_raporteaza_separat() -> None:
    reference = ReferenceListing(
        source="Wolt",
        phone="0722 889 982",
        postal_code="023756",
        hours=("11:00-21:30",),
        page_url="https://exemplu.ro/locatie-centru",
    )
    issues = find_nap_mismatches([_nap_page()], [reference], site_url="https://exemplu.ro/")
    fields = {issue.details["field"] for issue in issues}
    assert fields == {"phone", "postal_code", "hours"}
    assert all(issue.issue_type == "nap-mismatch" for issue in issues)
    phone_issue = next(i for i in issues if i.details["field"] == "phone")
    assert phone_issue.details["site_value"] == ["0773957224"]
    assert phone_issue.details["source"] == "Wolt"


def test_listarea_fara_pagina_corespunzatoare_e_raportata() -> None:
    reference = ReferenceListing(source="Google Business Profile", phone="0700 000 000")
    issues = find_nap_mismatches([_nap_page()], [reference], site_url="https://exemplu.ro/")
    assert [issue.details["field"] for issue in issues] == ["page"]


def test_nap_mismatch_nu_intra_in_scor() -> None:
    page = make_page()
    reference = ReferenceListing(source="X", phone="0700 000 000")
    issues = find_nap_mismatches([page], [reference], site_url="https://exemplu.ro/")
    assert compute_pillar_scores([page], issues) == compute_pillar_scores([page], [])


# --- bugetul de crawl ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://exemplu.ro/cart/", True),
        ("https://exemplu.ro/my-account/orders/", True),
        ("https://exemplu.ro/cosul-meu/", True),
        ("https://exemplu.ro/produs/?add-to-cart=12", True),
        ("https://exemplu.ro/cannoleria-titulescu/", False),
        ("https://exemplu.ro/account-based-marketing/", False),
    ],
)
def test_paginile_utilitare_se_recunosc(url: str, expected: bool) -> None:
    assert is_utility_url(url) is expected


def test_auditul_nu_crawleaza_cosul_si_compara_listarile() -> None:
    long_text = "cuvant " * 200
    pages = {
        "/": "<html><head><title>Acasa la Exemplu</title></head><body><h1>Acasa</h1>"
        f"<p>{long_text}</p><a href='/cart/'>Cos</a>"
        "<a href='/locatie-centru/'>Centru</a></body></html>",
        "/locatie-centru/": _location_html(),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path in ("/robots.txt", "/llms.txt", "/sitemap.xml", "/sitemap_index.xml"):
            return httpx.Response(404)
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(
                404, headers={"content-type": "text/html"}, text="<html>404</html>"
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)

    config = AuditConfig(
        max_pages=10,
        reference_listings=(
            ReferenceListing(source="Google Business Profile", phone="0722 889 982"),
        ),
    )
    result = asyncio.run(
        run_audit("https://exemplu.ro/", config, transport=httpx.MockTransport(handler))
    )
    assert "/cart/" not in requested
    types = {issue.issue_type for issue in result.issues}
    assert "missing-local-business-schema" in types
    assert "nap-mismatch" in types


# --- testul de prezenta ------------------------------------------------------------


def _hits(*urls: str, snippet: str = "") -> list[SearchHit]:
    return [
        SearchHit(title=f"Rezultat {i}", url=url, snippet=snippet) for i, url in enumerate(urls)
    ]


def test_pozitia_domeniului_propriu_se_masoara() -> None:
    result = evaluate_question(
        "cea mai buna pinsa bucuresti",
        _hits(
            "https://wanderlog.com/a", "https://www.exemplu.ro/pinsa", "https://tripadvisor.com/b"
        ),
        brand="Exemplu",
        domain="exemplu.ro",
    )
    assert result.own_domain_position == 2
    assert result.brand_mentioned is True


def test_brandul_citat_de_altii_conteaza_ca_prezenta() -> None:
    result = evaluate_question(
        "pinsa bucuresti",
        _hits("https://zilesinopti.ro/x", snippet="Top 5: Exemplu are cea mai buna pinsa"),
        brand="Exemplu",
        domain="exemplu.ro",
    )
    assert result.brand_mentioned is True
    assert result.own_domain_position is None


def test_brandul_absent_si_domeniile_concurente() -> None:
    answered = [
        evaluate_question(
            q,
            _hits("https://wanderlog.com/a", "https://tripadvisor.com/b"),
            brand="Exemplu",
            domain="exemplu.ro",
        )
        for q in ("pinsa bucuresti", "cannoli bucuresti")
    ]
    failed = QuestionPresence(question="restaurant italian", status="failed", error="timeout")
    report = evaluate_presence("Exemplu", "exemplu.ro", [*answered, failed])
    assert report.brand_presence_rate == 0.0
    assert report.own_domain_rate == 0.0
    assert report.competing_domains == [("wanderlog.com", 2), ("tripadvisor.com", 2)]
    assert len(report.questions) == 3  # intrebarea picata ramane in raport


class _FakeProvider:
    def __init__(self, results: dict[str, list[SearchHit]], fail: set[str] = frozenset()) -> None:
        self._results = results
        self._fail = fail

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        if query in self._fail:
            raise RuntimeError("limita de cautare")
        return self._results.get(query, [])[:max_results]


def test_o_cautare_picata_nu_e_brand_absent() -> None:
    provider = _FakeProvider({"a": _hits("https://exemplu.ro/")}, fail={"b"})
    report = asyncio.run(probe_presence("Exemplu", "exemplu.ro", ["a", "b"], provider))
    assert report.brand_presence_rate == 1.0
    assert [q.status for q in report.questions] == ["ok", "failed"]


@pytest.fixture
def presence_client(jwt_settings: None) -> Iterator[TestClient]:
    app = create_app()
    provider = _FakeProvider({"pinsa bucuresti": _hits("https://wanderlog.com/a")})
    app.dependency_overrides[router_module._get_search_provider] = lambda: provider
    with TestClient(app) as client:
        yield client


def test_endpointul_de_prezenta_cere_autentificare(presence_client: TestClient) -> None:
    response = presence_client.post(
        "/api/v1/seo-geo/presence",
        json={"brand": "Exemplu", "domain": "exemplu.ro", "questions": ["pinsa bucuresti"]},
    )
    assert response.status_code == 401


def test_endpointul_de_prezenta_intoarce_raportul(
    presence_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = presence_client.post(
        "/api/v1/seo-geo/presence",
        json={"brand": "Exemplu", "domain": "exemplu.ro", "questions": ["pinsa bucuresti"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["brand_presence_rate"] == 0.0
    assert body["competing_domains"] == [{"domain": "wanderlog.com", "count": 1}]
    assert body["questions"][0]["own_domain_position"] is None


def test_auditul_accepta_listari_externe(
    auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from seo_geo_agent.audit import url_policy

    async def _no_dns(_hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", _no_dns)
    captured: dict[str, AuditConfig] = {}

    async def _fake_runner(start_url: str, config: AuditConfig, on_progress: object) -> object:
        captured["config"] = config
        raise RuntimeError("oprit dupa captura")

    app = create_app()
    app.dependency_overrides[router_module._get_audit_runner] = lambda: _fake_runner
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/seo-geo/audit",
            json={
                "domain": "exemplu.ro",
                "reference_listings": [
                    {"source": "Wolt", "phone": "0722 889 982", "hours": ["11:00-21:30"]}
                ],
            },
            headers=auth_headers,
        )
    assert response.status_code == 202
    listing = captured["config"].reference_listings[0]
    assert listing.source == "Wolt"
    assert listing.hours == ("11:00-21:30",)
