"""Sursele de date organice si analizele hibride PPC+SEO.

Totul fara retea: ``httpx.MockTransport`` pentru cele doua cliente HTTP, functii
pure pentru analize. Testele tin invariantele de care depind deciziile de
buget - nu re-testeaza httpx.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from ppc_agent.errors import SetupRequiredError
from ppc_agent.search_data.insights import (
    CannibalizationDetector,
    OrganicPosition,
    PaidSearchTerm,
    SeoOpportunityFinder,
)
from ppc_agent.search_data.search_console import SearchConsoleClient, normalize_site_url
from ppc_agent.search_data.serp_tracker import (
    OpenSerpProvider,
    SerpCheck,
    check_rankings_sync,
    registrable_domain,
)


def _gsc_client(handler: object, **kwargs: object) -> SearchConsoleClient:
    return SearchConsoleClient(
        site_url=str(kwargs.pop("site_url", "exemplu.ro")),
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _oauth_then(rows_payload: dict[str, object]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake"})
        return httpx.Response(200, json=rows_payload)

    return handler


# --- Search Console ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("exemplu.ro", "sc-domain:exemplu.ro"),
        ("sc-domain:exemplu.ro", "sc-domain:exemplu.ro"),
        ("https://exemplu.ro", "https://exemplu.ro/"),
        ("https://exemplu.ro/", "https://exemplu.ro/"),
    ],
)
def test_proprietatea_se_normalizeaza_la_forma_ceruta_de_api(raw: str, expected: str) -> None:
    assert normalize_site_url(raw) == expected


def test_randurile_se_mapeaza_pe_dimensiunile_cerute() -> None:
    """``keys`` vine ca lista pozitionala - o mapare gresita ar amesteca tara cu pagina."""
    client = _gsc_client(
        _oauth_then(
            {
                "rows": [
                    {
                        "keys": [
                            "2026-09-20",
                            "pantofi piele",
                            "https://exemplu.ro/p",
                            "rou",
                            "MOBILE",
                        ],
                        "clicks": 12,
                        "impressions": 300,
                        "ctr": 0.04,
                        "position": 2.4,
                    }
                ]
            }
        )
    )
    (row,) = client.fetch_search_analytics(
        start_date=date(2026, 9, 20), end_date=date(2026, 9, 20)
    )
    assert (row.day, row.query, row.page, row.country, row.device) == (
        date(2026, 9, 20),
        "pantofi piele",
        "https://exemplu.ro/p",
        "rou",
        "MOBILE",
    )
    assert row.position == 2.4


def test_un_rand_malformat_nu_opreste_importul() -> None:
    """Pierdem randul, nu sincronizarea - altfel o zi intreaga ar lipsi din istoric."""
    client = _gsc_client(
        _oauth_then(
            {
                "rows": [
                    {"keys": ["prea", "putine"], "clicks": 1},
                    {
                        "keys": ["2026-09-20", "q", "u", "rou", "DESKTOP"],
                        "clicks": 1,
                        "impressions": 2,
                        "ctr": 0.5,
                        "position": 9.0,
                    },
                ]
            }
        )
    )
    rows = client.fetch_search_analytics(start_date=date(2026, 9, 20), end_date=date(2026, 9, 20))
    assert [row.query for row in rows] == ["q"]


def test_proprietate_neverificata_da_eroare_de_configurare() -> None:
    """403 e o problema pe care o rezolva utilizatorul, nu un retry."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake"})
        return httpx.Response(403, text="forbidden")

    client = _gsc_client(handler)
    with pytest.raises(SetupRequiredError, match="verificata"):
        client.fetch_search_analytics(start_date=date(2026, 9, 1), end_date=date(2026, 9, 2))


def test_paginarea_se_opreste_cand_raspunsul_e_incomplet() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake"})
        body = json.loads(request.content)
        calls.append(int(body["startRow"]))
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["2026-09-20", f"q{body['startRow']}", "u", "rou", "DESKTOP"],
                        "clicks": 1,
                        "impressions": 1,
                        "ctr": 1.0,
                        "position": 1.0,
                    }
                ]
            },
        )

    client = _gsc_client(handler)
    rows = client.fetch_search_analytics(
        start_date=date(2026, 9, 20), end_date=date(2026, 9, 20), max_rows=10
    )
    assert calls == [0]  # un rand < limita ceruta => gata, fara a doua cerere
    assert len(rows) == 1


# --- OpenSERP ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Exemplu.ro/pagina", "exemplu.ro"),
        ("exemplu.ro", "exemplu.ro"),
        ("http://sub.exemplu.ro", "sub.exemplu.ro"),
    ],
)
def test_domeniul_se_normalizeaza_pentru_comparatie(raw: str, expected: str) -> None:
    assert registrable_domain(raw) == expected


def _openserp(handler: object) -> OpenSerpProvider:
    return OpenSerpProvider(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _json_response(payload: object) -> object:
    return lambda request: httpx.Response(200, json=payload)


def _check(handler: object, keyword: str = "pantofi piele") -> SerpCheck:
    return asyncio.run(_openserp(handler).check_ranking(keyword, "exemplu.ro"))


def test_pozitia_se_numara_peste_rezultatele_organice() -> None:
    """Numaram noi, nu ne luam dupa 'rank' - acela include blocuri non-organice."""
    check = _check(
        _json_response(
            [
                {"type": "organic", "rank": 1, "url": "https://concurent1.ro/a", "title": "C1"},
                {"type": "organic", "rank": 4, "url": "https://www.concurent2.ro/b", "title": "C2"},
                {"type": "organic", "rank": 6, "url": "https://www.exemplu.ro/p", "title": "Noi"},
            ]
        )
    )
    assert check.status == "ok"
    assert check.position == 3
    assert check.url == "https://www.exemplu.ro/p"


def test_rezultatele_non_organice_nu_intra_in_numaratoare() -> None:
    check = _check(
        _json_response(
            [
                {"type": "ad", "url": "https://reclama.ro/x"},
                {"type": "organic", "url": "https://exemplu.ro/p"},
            ]
        )
    )
    assert check.position == 1


def test_se_retin_doar_concurentii_de_deasupra_noastra() -> None:
    """Cine e sub noi nu ne-a luat nimic - nu e concurent pentru interogarea asta."""
    check = _check(
        _json_response(
            [
                {"type": "organic", "url": "https://concurent1.ro/a"},
                {"type": "organic", "url": "https://exemplu.ro/x"},
                {"type": "organic", "url": "https://concurent2.ro/b"},
            ]
        )
    )
    assert [c.domain for c in check.competitors] == ["concurent1.ro"]


def test_domeniul_absent_e_un_raspuns_valid_nu_o_eroare() -> None:
    """"Nu ranchezi" e informatie reala; confuzia cu o eroare ar strica graficele."""
    check = _check(_json_response([{"type": "organic", "url": "https://altcineva.ro/a"}]))
    assert check.status == "ok"
    assert check.position is None


def test_raspunsul_infasurat_in_obiect_e_acceptat() -> None:
    """Variantele mai noi pot intoarce {"results": [...]} - nu cadem tacut la upgrade."""
    check = _check(_json_response({"results": [{"type": "organic", "url": "https://exemplu.ro/"}]}))
    assert check.position == 1


def test_instanta_oprita_da_unavailable_nu_exceptie() -> None:
    """Fara OpenSERP pornit, restul platformei trebuie sa mearga neschimbat."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    check = _check(refuse)
    assert check.status == "unavailable"
    assert "docker run" in check.message


def test_captcha_e_o_stare_distincta_de_eroare() -> None:
    """Raspunsul corect la o provocare anti-bot e oprirea, nu reincercarea."""
    check = _check(lambda request: httpx.Response(200, text="Our systems detected unusual traffic"))
    assert check.status == "blocked"


def test_429_e_tratat_tot_ca_blocare() -> None:
    check = _check(lambda request: httpx.Response(429, text="slow down"))
    assert check.status == "blocked"


def test_verificarea_in_bloc_pastreaza_ordinea_cuvintelor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params["text"]
        return httpx.Response(
            200, json=[{"type": "organic", "url": f"https://exemplu.ro/{keyword}"}]
        )

    checks = asyncio.run(
        _openserp(handler).check_rankings(["unu", "doi", "trei"], "exemplu.ro")
    )
    assert [c.keyword for c in checks] == ["unu", "doi", "trei"]
    assert all(c.position == 1 for c in checks)


def test_o_verificare_ratata_nu_le_opreste_pe_celelalte() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["text"] == "doi":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=[{"type": "organic", "url": "https://exemplu.ro/"}])

    checks = asyncio.run(_openserp(handler).check_rankings(["unu", "doi", "trei"], "exemplu.ro"))
    assert [c.status for c in checks] == ["ok", "error", "ok"]


def test_puntea_sincrona_intoarce_aceleasi_rezultate() -> None:
    """Joburile serverului sunt sincrone - au nevoie de un singur punct de traducere."""
    provider = _openserp(_json_response([{"type": "organic", "url": "https://exemplu.ro/"}]))
    checks = check_rankings_sync(provider, ["unu"], "exemplu.ro")
    assert [c.position for c in checks] == [1]


# --- Analizele hibride ------------------------------------------------------


def _paid(term: str, cost: str, conversions: float) -> PaidSearchTerm:
    return PaidSearchTerm(
        term=term,
        clicks=10,
        cost=Decimal(cost),
        conversions=conversions,
        conversions_value=Decimal("1000"),
    )


def test_canibalizarea_prinde_termenii_pe_care_ii_detinem_deja_organic() -> None:
    findings = CannibalizationDetector().find(
        [_paid("pantofi piele", "450.00", 6), _paid("cizme dama", "200.00", 4)],
        [OrganicPosition("Pantofi Piele", 2.1, 50, 900), OrganicPosition("cizme dama", 24.0, 2, 4)],
    )
    assert [f.term for f in findings] == ["pantofi piele"]
    assert findings[0].potential_monthly_saving == Decimal("450.00")


def test_potrivirea_termenilor_ignora_diacriticele_de_forma() -> None:
    """Cele doua surse scriu acelasi termen diferit; potrivirea se face normalizat."""
    findings = CannibalizationDetector().find(
        [_paid("  Pantofi   Piele ", "100", 1)],
        [OrganicPosition("pantofi piele", 1.2, 10, 100)],
    )
    assert len(findings) == 1


def test_oportunitatile_cer_conversii_reale_nu_doar_trafic() -> None:
    opportunities = SeoOpportunityFinder().find(
        [_paid("termen fara conversii", "300", 0), _paid("termen bun", "200", 4)],
        [],
    )
    assert [o.term for o in opportunities] == ["termen bun"]
    assert opportunities[0].organic_position is None


def test_un_termen_pe_care_deja_ranchezi_nu_e_oportunitate() -> None:
    opportunities = SeoOpportunityFinder().find(
        [_paid("termen bun", "200", 4)],
        [OrganicPosition("termen bun", 4.0, 10, 100)],
    )
    assert opportunities == []
