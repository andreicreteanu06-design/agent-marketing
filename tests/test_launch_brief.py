"""Brief-ul de lansare: ce spun agentii SEO/GEO si PPC inainte de coada de aprobari.

Furnizorii sunt cei ``mock`` ai proiectului (deterministi, fara retea), cu cate o
piesa inlocuita pentru fiecare scenariu. Ce se verifica e regula brief-ului:
blocheaza doar ce e obiectiv, ridica la avertisment doar ce costa bani, si nu
inventeaza nimic acolo unde n-are date.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.config import AppConfig, BudgetConfig, ProviderMode, Settings
from ppc_agent.errors import (
    CrawlBlockedError,
    CrawlError,
    CrawlTargetBlockedError,
    CrawlTimeoutError,
    SetupRequiredError,
)
from ppc_agent.providers.base import CrawlerProvider, FetchResult
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.meta_campaign import MetaLaunchSpec
from ppc_agent.services.launch_brief import LaunchBrief, build_launch_brief, pixel_presence

_URL = "https://exemplu.ro/oferta"
_PIXEL = "1234567890"
_WORDS = " ".join(["revizie"] * 200)
_GOOD_HTML = (
    "<html><head><title>Service auto Bucuresti - revizii rapide</title>"
    '<meta name="description" content="Revizii complete, diagnoza gratuita si piese '
    'originale, cu programare online in aceeasi zi.">'
    f"<script>fbq('init', '{_PIXEL}');</script>"
    '<script src="https://connect.facebook.net/en_US/fbevents.js"></script>'
    f"</head><body><h1>Revizie completa in 24h</h1><p>{_WORDS}</p>"
    '<a href="/contact">Contact</a></body></html>'
)


def _config(
    *,
    target_cpa: str | None = "300",
    mode: ProviderMode = ProviderMode.MOCK,
    **settings: Any,
) -> AppConfig:
    return AppConfig(
        target_domain="exemplu.ro",
        budget=BudgetConfig(
            max_daily_spend=Decimal("50"),
            target_cpa=Decimal(target_cpa) if target_cpa is not None else None,
        ),
        settings=Settings(provider_mode=mode, **settings),
    )


def _spec(**overrides: Any) -> MetaLaunchSpec:
    fields: dict[str, Any] = {
        "campaign_name": "Service Auto - Vanzari",
        "objective": CampaignObjective.SALES,
        "daily_budget": Decimal("25.00"),
        "pixel_id": _PIXEL,
        "custom_event_type": "PURCHASE",
        "page_id": "9876543210",
        "target_url": _URL,
        "headline": "Revizie completa in 24h",
        "primary_text": "Programeaza revizia online.",
        "image_url": "https://cdn.exemplu.ro/reclama.jpg",
        "country": "RO",
        "call_to_action": "SHOP_NOW",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)


class _Crawler(CrawlerProvider):
    """Intoarce mereu acelasi rezultat - sau ridica aceeasi exceptie."""

    def __init__(self, outcome: FetchResult | Exception) -> None:
        self._outcome = outcome

    def fetch(self, url: str) -> FetchResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    def robots_txt(self, base_url: str) -> str | None:
        return None


def _page(html: str = _GOOD_HTML, status: int = 200) -> _Crawler:
    return _Crawler(FetchResult(_URL, _URL, status, html, ok=200 <= status < 300))


class _Down:
    """Un furnizor fara credentiale: orice metoda chemata pica."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise SetupRequiredError(f"{name}: lipsesc credentialele")

        return fail


class _Returns:
    """Un furnizor care intoarce o valoare fixa, oricare ar fi metoda."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: self._value


class _Sources:
    """``ProviderFactory`` in modul dat, cu piesele primite inlocuite."""

    def __init__(self, config: AppConfig, **replacements: Any) -> None:
        self._factory = ProviderFactory(config)
        self._replacements = replacements

    def _pick(self, name: str) -> Any:
        return self._replacements.get(name) or getattr(self._factory, name)()

    def crawler(self) -> Any:
        return self._pick("crawler")

    def gsc(self) -> Any:
        return self._pick("gsc")

    def keyword_planner(self) -> Any:
        return self._pick("keyword_planner")

    def gbp(self) -> Any:
        return self._pick("gbp")

    def meta(self) -> Any:
        return self._pick("meta")


def _brief(
    config: AppConfig | None = None,
    spec: MetaLaunchSpec | None = None,
    committed: str = "0",
    **replacements: Any,
) -> LaunchBrief:
    config = config or _config()
    replacements.setdefault("crawler", _page())
    return build_launch_brief(
        _Sources(config, **replacements),
        config,
        spec or _spec(),
        ad_account="act_555",
        committed_daily_spend=Decimal(committed),
    )


# --- brief-ul complet -------------------------------------------------------


def test_brief_complet_din_furnizorii_mock() -> None:
    config = _config()
    brief = build_launch_brief(ProviderFactory(config), config, _spec(), ad_account="act_555")
    payload = brief.to_payload()

    json.dumps(payload)  # se salveaza intr-o coloana JSON - trebuie sa fie serializabil
    assert payload["landing_page"]["status"] == "ok"
    assert payload["learning_phase"]["status"] == "ok"
    assert payload["budget_position"]["status"] == "ok"
    signals = payload["message_signals"]
    assert signals["gsc"]["status"] == "ok"
    assert signals["keyword_planner"]["status"] == "ok"
    assert signals["gbp"]["status"] == "ok"
    assert payload["verdict"] in ("ok", "warnings")
    assert payload["blocking"] == []


def test_markov_e_declarat_explicit_in_afara_deciziei() -> None:
    """Nu se preface ca a calculat ceva: o campanie inexistenta n-are parcursuri."""
    assert "nu intra" in _brief().to_payload()["markov"]


# --- pagina de destinatie: ce blocheaza -------------------------------------


@pytest.mark.parametrize("status", [404, 410])
def test_o_pagina_care_nu_exista_blocheaza_lansarea(status: int) -> None:
    brief = _brief(crawler=_page("<html>nu exista</html>", status=status))
    assert brief.verdict == "blocked"
    assert str(status) in brief.blocking[0]
    assert brief.landing_page["status"] == "gone"


def test_o_adresa_care_nu_e_publica_blocheaza_lansarea() -> None:
    brief = _brief(crawler=_Crawler(CrawlTargetBlockedError("adresa privata")))
    assert brief.verdict == "blocked"
    assert brief.landing_page["status"] == "not_public"


@pytest.mark.parametrize(
    "error",
    [
        CrawlBlockedError("403 challenge"),
        CrawlTimeoutError("15s"),
        CrawlError("dns"),
        RuntimeError("ceva neasteptat"),
    ],
)
def test_ce_nu_e_sigur_stricat_ramane_avertisment(error: Exception) -> None:
    """Un crawler oprit de site sau o retea capricioasa nu dovedesc o pagina moarta."""
    brief = _brief(crawler=_Crawler(error))
    assert brief.blocking == []
    assert brief.landing_page["status"] == "unverified"
    assert any("pagina" in warning for warning in brief.warnings)


# --- pagina de destinatie: ce conteaza pentru bani --------------------------


def test_noindex_nu_devine_avertisment() -> None:
    """Paginile de reclama sunt des noindex intentionat - nu e o problema pentru Meta."""
    html = _GOOD_HTML.replace("<head>", '<head><meta name="robots" content="noindex">')
    brief = _brief(crawler=_page(html))

    seo_only = {issue["id"]: issue for issue in brief.landing_page["seo_only_issues"]}
    assert "noindex-page" in seo_only
    assert "normal pentru paginile de reclama" in seo_only["noindex-page"]["for_paid_traffic"]
    assert not any("noindex" in warning.lower() for warning in brief.warnings)


def test_doar_problemele_care_costa_bani_devin_avertismente() -> None:
    html = (
        "<html><head><title>Service auto Bucuresti - revizii rapide</title></head>"
        f"<body><p>{_WORDS}</p><script>fbq('init', '{_PIXEL}');</script></body></html>"
    )
    brief = _brief(crawler=_page(html))

    paid = {issue["id"] for issue in brief.landing_page["paid_traffic_issues"]}
    seo_only = {issue["id"] for issue in brief.landing_page["seo_only_issues"]}
    assert "missing-h1" in paid
    assert "missing-meta-description" in seo_only
    assert any("pagina de destinatie" in warning for warning in brief.warnings)
    assert not any("meta description" in warning.lower() for warning in brief.warnings)


def test_problemele_poarta_textul_si_remedierea_din_auditul_seo() -> None:
    html = _GOOD_HTML.replace("<h1>Revizie completa in 24h</h1>", "")
    brief = _brief(crawler=_page(html))
    (issue,) = [i for i in brief.landing_page["paid_traffic_issues"] if i["id"] == "missing-h1"]
    assert issue["title"]
    assert issue["how_to_fix"]
    assert issue["severity"] in ("critical", "warning", "info")


def test_o_pagina_buna_nu_are_avertismente_de_pagina() -> None:
    brief = _brief()
    assert brief.landing_page["paid_traffic_issues"] == []
    assert brief.landing_page["pixel"] == "found"
    assert brief.landing_page["h1"] == ["Revizie completa in 24h"]


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (f"<script>fbq('init', '{_PIXEL}');</script>", "found"),
        ("<script>fbq('init', '999999');</script>", "other_pixel"),
        ('<script src="https://www.googletagmanager.com/gtm.js?id=GTM-X"></script>', "tag_manager"),
        ("<p>nimic</p>", "missing"),
    ],
)
def test_pixelul_se_cauta_in_html_ul_paginii(html: str, expected: str) -> None:
    assert pixel_presence(html, _PIXEL) == expected


def test_un_alt_pixel_pe_pagina_e_avertisment() -> None:
    html = _GOOD_HTML.replace(f"'{_PIXEL}'", "'999999'")
    brief = _brief(crawler=_page(html))
    assert any("alt pixel" in warning for warning in brief.warnings)


# --- faza de invatare -------------------------------------------------------


def test_25_de_lei_pe_zi_nu_iese_din_faza_de_invatare() -> None:
    """25 RON/zi la un CPA de 300: ~0,6 evenimente pe saptamana, fata de ~50."""
    section = _brief().learning_phase

    assert section["exits_learning"] is False
    assert section["days_to_exit"] is None
    assert section["expected_events_per_week"] == "0.6"
    assert section["max_cpa_to_exit"] == "3.50"
    assert section["budget_needed_at_target_cpa"] == "2142.86"
    assert section["capacity"]["tier"] == "micro"


def test_learning_limited_e_avertisment_nu_blocaj() -> None:
    """Un test mic intentionat trebuie sa poata intra in coada."""
    brief = _brief()
    assert brief.blocking == []
    assert any("Learning Limited" in warning for warning in brief.warnings)


def test_un_buget_suficient_iese_din_faza_de_invatare() -> None:
    # 500/zi la CPA 20 = 25 evenimente/zi = 175/saptamana -> 50 in 2 zile.
    brief = _brief(config=_config(target_cpa="20"), spec=_spec(daily_budget=Decimal("500")))
    section = brief.learning_phase
    assert section["exits_learning"] is True
    assert section["days_to_exit"] == 2.0
    assert not any("Learning Limited" in warning for warning in brief.warnings)


def test_fara_cpa_tinta_faza_de_invatare_nu_se_ghiceste() -> None:
    brief = _brief(config=_config(target_cpa=None))
    assert brief.learning_phase["status"] == "unavailable"


# --- Kelly si Thompson ------------------------------------------------------


def test_fara_istoric_kelly_si_thompson_nu_inventeaza_nimic() -> None:
    empty = pd.DataFrame(columns=["arm_id", "name", "clicks", "conversions", "cost", "revenue"])
    section = _brief(meta=_Returns(empty)).budget_position

    assert section["status"] == "no_history"
    assert "explorare" in section["note"]
    assert "kelly" not in section


def test_kelly_avertizeaza_cand_angajamentul_trece_de_plafon() -> None:
    brief = _brief(committed="10000")
    assert brief.budget_position["status"] == "ok"
    assert any(warning.startswith("Kelly:") for warning in brief.warnings)


def test_thompson_da_tinta_pe_care_campania_noua_trebuie_s_o_bata() -> None:
    brief = _brief()
    thompson = brief.budget_position["thompson"]

    assert thompson["status"] == "ok"
    assert thompson["best_cpa"] is not None
    # Campania noua nu e brat: fara date, priorul Beta(1,1) ar face-o sa "castige".
    assert thompson["best_arm"] != _spec().campaign_name
    assert any(suggestion.startswith("Thompson:") for suggestion in brief.suggestions)


def test_acelasi_istoric_da_acelasi_brief() -> None:
    first = _brief().budget_position["thompson"]
    second = _brief().budget_position["thompson"]
    assert first == second


# --- semnale pentru mesaj ---------------------------------------------------


def test_o_sursa_picata_apare_ca_indisponibila_si_nu_opreste_brief_ul() -> None:
    brief = _brief(gsc=_Down(), keyword_planner=_Down(), gbp=_Down(), meta=_Down())

    signals = brief.message_signals
    assert signals["gsc"]["status"] == "unavailable"
    assert signals["keyword_planner"]["status"] == "unavailable"
    assert signals["gbp"]["status"] == "unavailable"
    assert brief.budget_position["status"] == "unavailable"
    assert brief.blocking == []


def test_fara_locatie_gbp_in_modul_live_nu_se_face_nicio_cerere() -> None:
    class _NeverCalled:
        def local_signals(self, location_id: str) -> Any:
            raise AssertionError("GBP nu trebuia chemat fara locatie configurata")

    config = _config(mode=ProviderMode.LIVE, gbp_location_id="")
    brief = _brief(
        config=config,
        gsc=_Down(),
        keyword_planner=_Down(),
        meta=_Down(),
        gbp=_NeverCalled(),
    )
    assert brief.message_signals["gbp"]["status"] == "unavailable"
    assert "PPC_GBP_LOCATION_ID" in brief.message_signals["gbp"]["reason"]


def _gbp(rating: float, count: int) -> _Returns:
    return _Returns(
        {
            "name": "Service Auto Popescu",
            "categories": ["Atelier auto"],
            "review_count": count,
            "avg_rating": rating,
            "reviews": [{"text": "ok", "score": 0.0, "label": "neutru"}],
        }
    )


def test_un_rating_gbp_slab_e_avertisment() -> None:
    brief = _brief(gbp=_gbp(3.4, 20))
    assert any("Business Profile" in warning for warning in brief.warnings)


def test_un_rating_gbp_bun_devine_dovada_sociala() -> None:
    brief = _brief(gbp=_gbp(4.7, 213))
    assert any("dovada sociala" in suggestion for suggestion in brief.suggestions)


def _gsc(*queries: str) -> _Returns:
    return _Returns(
        pd.DataFrame(
            [
                {
                    "query": query,
                    "clicks": 100 - i,
                    "impressions": 1000,
                    "ctr": 0.1,
                    "position": 3.0,
                }
                for i, query in enumerate(queries)
            ]
        )
    )


def test_textul_care_ignora_cautarile_reale_primeste_o_sugestie() -> None:
    brief = _brief(gsc=_gsc("service auto bucuresti", "reparatii auto", "vulcanizare"))
    assert any("nu foloseste niciunul" in suggestion for suggestion in brief.suggestions)


def test_textul_care_foloseste_cautarile_reale_nu_primeste_sugestia() -> None:
    brief = _brief(
        gsc=_gsc("service auto bucuresti", "reparatii auto"),
        spec=_spec(headline="Service auto in 24h"),
    )
    assert not any("nu foloseste niciunul" in suggestion for suggestion in brief.suggestions)


def test_rezumatul_numara_ce_contine_brief_ul() -> None:
    brief = _brief(crawler=_page("<html>nu exista</html>", status=404))
    assert brief.summary().startswith("Brief de lansare: blocata - 1 blocaje")


# --- reguli post-Andromeda --------------------------------------------------


def test_reclame_aproape_identice_ajung_in_avertismentele_brief_ului() -> None:
    from ppc_agent.providers.meta_campaign import MetaAdCreative

    twin = MetaAdCreative(
        "Revizie completa in 24h", "Programeaza revizia online azi.", "https://cdn.exemplu.ro/b.jpg"
    )
    brief = _brief(spec=_spec(extra_ads=(twin,)))
    assert any("aproape acelasi lucru" in warning for warning in brief.warnings)


def test_o_singura_reclama_la_buget_mare_primeste_sugestia_de_diversitate() -> None:
    brief = _brief(config=_config(target_cpa="5"), spec=_spec(daily_budget=Decimal("100")))
    assert any("diversitate" in suggestion for suggestion in brief.suggestions)
