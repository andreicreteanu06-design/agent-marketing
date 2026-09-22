"""Sursele de date organice si analizele hibride PPC+SEO.

Totul fara retea: ``httpx.MockTransport`` pentru cele doua cliente HTTP, functii
pure pentru analize. Testele tin invariantele de care depind deciziile de
buget - nu re-testeaza httpx.
"""

from __future__ import annotations

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
from ppc_agent.search_data.serp_tracker import SerperSerpProvider, registrable_domain


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


# --- Serper -----------------------------------------------------------------


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


def _serp(payload: dict[str, object], **kwargs: object) -> SerperSerpProvider:
    return SerperSerpProvider(
        api_key=str(kwargs.pop("api_key", "cheie")),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )


def test_pozitia_se_numara_peste_rezultatele_organice() -> None:
    """Numaram noi, nu ne luam dupa campul 'position' din raspuns - el poate sari."""
    provider = _serp(
        {
            "organic": [
                {"link": "https://concurent1.ro/a", "title": "C1"},
                {"link": "https://www.concurent2.ro/b", "title": "C2"},
                {"link": "https://www.exemplu.ro/pagina", "title": "Noi"},
            ]
        }
    )
    check = provider.check_ranking("pantofi piele", "exemplu.ro")
    assert check.status == "ok"
    assert check.position == 3
    assert check.url == "https://www.exemplu.ro/pagina"


def test_se_retin_doar_concurentii_de_deasupra_noastra() -> None:
    """Cine e sub noi nu ne-a luat nimic - nu e concurent pentru interogarea asta."""
    provider = _serp(
        {
            "organic": [
                {"link": "https://concurent1.ro/a"},
                {"link": "https://exemplu.ro/x"},
                {"link": "https://concurent2.ro/b"},
            ]
        }
    )
    check = provider.check_ranking("k", "exemplu.ro")
    assert [c.domain for c in check.competitors] == ["concurent1.ro"]


def test_domeniul_absent_e_un_raspuns_valid_nu_o_eroare() -> None:
    """"Nu ranchezi" e informatie reala; confuzia cu o eroare ar strica graficele."""
    provider = _serp({"organic": [{"link": "https://altcineva.ro/a"}]})
    check = provider.check_ranking("k", "exemplu.ro")
    assert check.status == "ok"
    assert check.position is None


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(429, "no_credits"), (401, "not_configured"), (403, "not_configured"), (500, "error")],
)
def test_esecurile_nu_arunca_ci_se_raporteaza(status_code: int, expected: str) -> None:
    """O verificare ratata nu are voie sa opreasca sincronizarea celorlalte cuvinte."""
    provider = SerperSerpProvider(
        api_key="cheie",
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, text="x")),
    )
    assert provider.check_ranking("k", "exemplu.ro").status == expected


def test_fara_cheie_nu_se_face_niciun_apel() -> None:
    def explode(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nu trebuia sa se faca niciun apel fara cheie")

    provider = SerperSerpProvider(transport=httpx.MockTransport(explode))
    assert provider.configured is False
    assert provider.check_ranking("k", "exemplu.ro").status == "not_configured"


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
