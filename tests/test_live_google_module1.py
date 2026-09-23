"""Furnizorii live ai Modulului 1: Search Console, Keyword Planner, Business Profile.

Fara retea reala: totul prin ``httpx.MockTransport``, ca la ceilalti furnizori
live. Ce se verifica nu e "merge apelul", ci lucrurile care strica tacut
rapoarte: constantele de limba/tara cerute de la Google in loc sa fie ghicite,
micro-unitatile convertite corect, si accesul neaprobat semnalat ca atare.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.live.gbp import LiveGbpProvider, split_location_ref
from ppc_agent.providers.live.keyword_planner import LiveKeywordPlannerProvider
from ppc_agent.providers.live.search_console import LiveGscProvider

_OAUTH_URL = "https://oauth2.googleapis.com/token"


def _oauth(request: httpx.Request) -> httpx.Response | None:
    """Raspunsul comun de OAuth; ``None`` cand cererea nu e catre OAuth."""
    if str(request.url) == _OAUTH_URL:
        return httpx.Response(200, json={"access_token": "token-viu"})
    return None


# --- Search Console ---------------------------------------------------------


def _gsc(handler: object, **kwargs: Any) -> LiveGscProvider:
    return LiveGscProvider(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kwargs,
    )


def test_gsc_cere_agregarea_pe_interogare_nu_istoric_zilnic() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        import json

        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["service auto"],
                        "clicks": 120,
                        "impressions": 4000,
                        "ctr": 0.03,
                        "position": 4.28,
                    },
                    {
                        "keys": ["cizme"],
                        "clicks": 1,
                        "impressions": 12,
                        "ctr": 0.083,
                        "position": 44.0,
                    },
                ]
            },
        )

    frame = _gsc(handler, site_url="sc-domain:exemplu.ro").top_queries("https://exemplu.ro")

    assert bodies[0]["dimensions"] == ["query"]
    assert list(frame.columns) == ["query", "clicks", "impressions", "ctr", "position"]
    # 12 afisari < pragul implicit de 100 - randul nu trebuie sa ajunga in seminte.
    assert frame["query"].tolist() == ["service auto"]
    assert frame.iloc[0]["position"] == 4.3


def test_gsc_foloseste_proprietatea_configurata_nu_domeniul_ghicit() -> None:
    """Dintr-un domeniu nu poti sti daca proprietatea e de tip domeniu sau prefix URL."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        seen.append(str(request.url))
        return httpx.Response(200, json={"rows": []})

    _gsc(handler, site_url="https://exemplu.ro/").top_queries("exemplu.ro")
    assert "https%3A%2F%2Fexemplu.ro%2F" in seen[0]


def test_gsc_fara_randuri_da_tabel_gol_cu_coloanele_corecte() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        return httpx.Response(200, json={})

    frame = _gsc(handler, site_url="sc-domain:exemplu.ro").top_queries("exemplu.ro")
    assert frame.empty
    assert list(frame.columns) == ["query", "clicks", "impressions", "ctr", "position"]


def test_gsc_fara_credentiale_nu_face_nicio_cerere() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    provider = LiveGscProvider(
        site_url="sc-domain:exemplu.ro",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )
    with pytest.raises(SetupRequiredError):
        provider.top_queries("exemplu.ro")


# --- Keyword Planner --------------------------------------------------------


def _planner(handler: object) -> LiveKeywordPlannerProvider:
    return LiveKeywordPlannerProvider(
        developer_token="dev",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        customer_id="1234567890",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _planner_handler(
    ideas: list[dict[str, Any]],
    *,
    language_rows: list[dict[str, Any]] | None = None,
    geo_rows: list[dict[str, Any]] | None = None,
    calls: list[str] | None = None,
) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if url.endswith(":generateKeywordIdeas"):
            return httpx.Response(200, json={"results": ideas})
        body = request.content.decode()
        if "language_constant" in body:
            rows = language_rows if language_rows is not None else [
                {"languageConstant": {"resourceName": "languageConstants/1038"}}
            ]
            return httpx.Response(200, json={"results": rows})
        rows = geo_rows if geo_rows is not None else [
            {"geoTargetConstant": {"resourceName": "geoTargetConstants/2642"}}
        ]
        return httpx.Response(200, json={"results": rows})

    return handler


def test_constantele_de_limba_si_tara_se_cer_de_la_google() -> None:
    """Id-urile de limba nu se deduc din codul ISO - o constanta gresita ar
    intoarce tacut volume pentru alta limba."""
    import json

    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        if str(request.url).endswith(":generateKeywordIdeas"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"results": []})
        body = request.content.decode()
        if "language_constant" in body:
            assert "'ro'" in body
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"languageConstant": {"resourceName": "languageConstants/1038"}}
                    ]
                },
            )
        assert "'RO'" in body
        return httpx.Response(
            200,
            json={
                "results": [
                    {"geoTargetConstant": {"resourceName": "geoTargetConstants/2642"}}
                ]
            },
        )

    _planner(handler).expand(["service auto"], "RO", "ro")
    assert sent[0]["language"] == "languageConstants/1038"
    assert sent[0]["geoTargetConstants"] == ["geoTargetConstants/2642"]


def test_constantele_se_cer_o_singura_data_pe_instanta() -> None:
    calls: list[str] = []
    provider = _planner(_planner_handler([], calls=calls))
    provider.expand(["a"], "RO", "ro")
    provider.expand(["b"], "RO", "ro")
    searches = [url for url in calls if url.endswith("googleAds:search")]
    assert len(searches) == 2  # o data limba, o data tara - nu de patru ori


def test_bidurile_vin_in_micro_unitati() -> None:
    ideas = [
        {
            "text": "service auto bucuresti",
            "keywordIdeaMetrics": {
                "avgMonthlySearches": "2400",
                "competitionIndex": "72",
                "lowTopOfPageBidMicros": "1250000",
                "highTopOfPageBidMicros": "4800000",
            },
        }
    ]
    frame = _planner(_planner_handler(ideas)).expand(["service auto"], "RO", "ro")
    row = frame.iloc[0]
    assert row["avg_monthly_searches"] == 2400
    assert row["low_top_bid"] == 1.25
    assert row["high_top_bid"] == 4.8
    assert row["competition"] == 0.72
    assert row["match_type_suggestion"] == "phrase"


def test_competitia_cade_pe_mijlocul_galetii_cand_lipseste_indexul() -> None:
    """Un cont fara cheltuiala primeste deseori doar eticheta, nu si indexul."""
    ideas = [{"text": "reparatii auto", "keywordIdeaMetrics": {"competition": "LOW"}}]
    frame = _planner(_planner_handler(ideas)).expand(["auto"], "RO", "ro")
    assert frame.iloc[0]["competition"] == 0.17
    assert frame.iloc[0]["match_type_suggestion"] == "exact"
    assert frame.iloc[0]["avg_monthly_searches"] == 0


def test_fara_seminte_nu_se_cheama_api_ul() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nu ar trebui sa faca niciun apel HTTP")

    frame = _planner(handler).expand(["", "  "], "RO", "ro")
    assert frame.empty
    assert next(iter(frame.columns)) == "keyword"


def test_o_tara_necunoscuta_e_eroare_de_configurare_nu_tabel_gol() -> None:
    provider = _planner(_planner_handler([], geo_rows=[]))
    with pytest.raises(SetupRequiredError, match="PPC_GEO"):
        provider.expand(["service auto"], "XX", "ro")


def test_ideile_duplicate_se_pastreaza_o_singura_data() -> None:
    ideas = [
        {"text": "service auto", "keywordIdeaMetrics": {"avgMonthlySearches": "10"}},
        {"text": "service auto", "keywordIdeaMetrics": {"avgMonthlySearches": "99"}},
    ]
    frame = _planner(_planner_handler(ideas)).expand(["auto"], "RO", "ro")
    assert len(frame) == 1
    assert frame.iloc[0]["avg_monthly_searches"] == 10


# --- Business Profile -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "fallback", "expected"),
    [
        ("accounts/111/locations/222", "", ("111", "222")),
        ("locations/222", "999", ("999", "222")),
        ("222", "999", ("999", "222")),
        ("222", "", ("", "222")),
    ],
)
def test_referinta_de_locatie_se_accepta_in_toate_formele(
    raw: str, fallback: str, expected: tuple[str, str]
) -> None:
    """Google insusi le amesteca intre cele doua API-uri."""
    assert split_location_ref(raw, fallback_account_id=fallback) == expected


def _gbp(handler: object, **kwargs: Any) -> LiveGbpProvider:
    return LiveGbpProvider(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kwargs,
    )


def _gbp_handler(
    *,
    info: dict[str, Any] | None = None,
    reviews: dict[str, Any] | None = None,
    info_status: int = 200,
    reviews_status: int = 200,
) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        if "mybusinessbusinessinformation" in str(request.url):
            return httpx.Response(info_status, json=info or {})
        return httpx.Response(reviews_status, json=reviews or {})

    return handler


def test_semnalele_locale_combina_cele_doua_api_uri() -> None:
    info = {
        "title": "Service Auto Popescu",
        "categories": {
            "primaryCategory": {"displayName": "Atelier auto"},
            "additionalCategories": [{"displayName": "Vulcanizare"}],
        },
    }
    reviews = {
        "averageRating": 4.6,
        "totalReviewCount": 213,
        "reviews": [
            {"starRating": "FIVE", "comment": "Servicii excelente, recomand cu incredere."},
            {"starRating": "ONE", "comment": "Groaznic, lucrare nereusita si pret mare."},
        ],
    }
    signals = _gbp(_gbp_handler(info=info, reviews=reviews), account_id="111").local_signals(
        "locations/222"
    )

    assert signals["name"] == "Service Auto Popescu"
    assert signals["categories"] == ["Atelier auto", "Vulcanizare"]
    assert signals["review_count"] == 213
    assert signals["avg_rating"] == 4.6
    scored = signals["reviews"]
    assert isinstance(scored, list)
    assert len(scored) == 2
    assert all("score" in entry and "label" in entry for entry in scored)


def test_recenziile_fara_text_intra_in_medie_dar_nu_in_sentiment() -> None:
    reviews = {
        "reviews": [
            {"starRating": "FOUR", "comment": "Multumit de serviciu."},
            {"starRating": "TWO"},
        ]
    }
    signals = _gbp(
        _gbp_handler(info={"title": "X"}, reviews=reviews), account_id="111"
    ).local_signals("222")

    assert len(signals["reviews"]) == 1  # type: ignore[arg-type]
    assert signals["review_count"] == 2
    assert signals["avg_rating"] == 3.0  # (4 + 2) / 2


def test_fara_cont_configurat_intoarce_semnale_partiale_nu_eroare() -> None:
    """Un semnal partial e mai util decat o eroare; review_count=0 o spune singur."""

    def handler(request: httpx.Request) -> httpx.Response:
        oauth = _oauth(request)
        if oauth is not None:
            return oauth
        if "mybusinessbusinessinformation" in str(request.url):
            return httpx.Response(200, json={"title": "Service Auto Popescu"})
        raise AssertionError("API-ul de recenzii nu ar trebui chemat fara cont")

    signals = _gbp(handler).local_signals("222")
    assert signals["name"] == "Service Auto Popescu"
    assert signals["review_count"] == 0
    assert signals["reviews"] == []


def test_accesul_neaprobat_e_semnalat_ca_atare() -> None:
    """403 aici inseamna de obicei cerere de acces inca nerezolvata de Google."""
    provider = _gbp(_gbp_handler(info_status=403), account_id="111")
    with pytest.raises(SetupRequiredError, match="Basic API Access"):
        provider.local_signals("222")


def test_o_eroare_de_server_ramane_provider_error() -> None:
    provider = _gbp(_gbp_handler(info_status=500), account_id="111")
    with pytest.raises(ProviderError):
        provider.local_signals("222")


# --- lantul complet ---------------------------------------------------------


def test_modulul_1_ruleaza_cap_coada_cu_toti_furnizorii_live() -> None:
    """Proba ca cele patru contracte chiar se potrivesc intre ele.

    Riscul real nu e ca un apel pica, ci ca un furnizor live intoarce alte
    coloane decat asteapta pipeline-ul - lucru pe care testele per furnizor
    nu-l prind. Aici trece tot Modulul 1, fara mock in mijloc.
    """
    from ppc_agent.config import AppConfig, ProviderMode, Settings
    from ppc_agent.ingestion.pipeline import run_ingestion
    from ppc_agent.providers.live.crawler import LiveCrawlerProvider

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == _OAUTH_URL:
            return httpx.Response(200, json={"access_token": "token-viu"})
        if "searchAnalytics" in url:
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "keys": ["program facturare"],
                            "clicks": 90,
                            "impressions": 3000,
                            "ctr": 0.03,
                            "position": 6.2,
                        }
                    ]
                },
            )
        if "mybusinessbusinessinformation" in url:
            return httpx.Response(
                200,
                json={
                    "title": "FacturarePro SRL",
                    "categories": {"primaryCategory": {"displayName": "Software company"}},
                },
            )
        if "mybusiness.googleapis.com" in url:
            return httpx.Response(
                200,
                json={
                    "averageRating": 4.4,
                    "totalReviewCount": 12,
                    "reviews": [{"starRating": "FIVE", "comment": "Aplicatie excelenta."}],
                },
            )
        if url.endswith(":generateKeywordIdeas"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "text": "program facturare pfa",
                            "keywordIdeaMetrics": {
                                "avgMonthlySearches": "880",
                                "competitionIndex": "40",
                                "lowTopOfPageBidMicros": "900000",
                                "highTopOfPageBidMicros": "2600000",
                            },
                        }
                    ]
                },
            )
        if "googleAds:search" in url:
            body = request.content.decode()
            key = "languageConstant" if "language_constant" in body else "geoTargetConstant"
            return httpx.Response(200, json={"results": [{key: {"resourceName": f"{key}s/1"}}]})
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            html=(
                "<html><head><title>Program facturare</title></head>"
                "<body><h1>Program facturare</h1><h2>Preturi</h2>"
                '<a href="/demo">Cere o oferta</a></body></html>'
            ),
        )

    transport = httpx.MockTransport(handler)

    class _LiveFactory:
        """Fabrica reala, dar cu transportul injectat - altfel ar iesi in retea."""

        def crawler(self) -> LiveCrawlerProvider:
            return LiveCrawlerProvider(transport=transport)

        def gsc(self) -> LiveGscProvider:
            return _gsc(handler, site_url="sc-domain:exemplu.ro")

        def gbp(self) -> LiveGbpProvider:
            return _gbp(handler, account_id="111", location_id="222")

        def keyword_planner(self) -> LiveKeywordPlannerProvider:
            return _planner(handler)

    config = AppConfig(
        target_domain="exemplu.ro",
        settings=Settings(provider_mode=ProviderMode.LIVE, gbp_location_id="222"),
    )
    result = run_ingestion(_LiveFactory(), "https://exemplu.ro/", config)  # type: ignore[arg-type]

    assert result.page_context.ok is True
    assert result.page_context.title == "Program facturare"
    assert result.local_signals is not None
    assert result.local_signals.name == "FacturarePro SRL"
    assert [seed.query for seed in result.seed_keywords] == ["program facturare"]
    assert any(
        item.keyword == "program facturare pfa" for item in result.expanded_keywords
    )
