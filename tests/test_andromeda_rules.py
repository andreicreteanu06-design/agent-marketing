"""Reguli post-Andromeda: diversitate reala, hook specific, numar de reclame pe masura bugetului."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.decision.andromeda_rules import (
    is_generic_hook,
    portfolio_findings,
    similar_pairs,
)
from ppc_agent.providers.meta_campaign import (
    LAUNCH_SPEC_VERSION,
    LAUNCH_SPEC_VERSION_MULTI_AD,
    MAX_ADS_PER_LAUNCH,
    LaunchResult,
    MetaAdCreative,
    MetaLaunchSpec,
    ad_fields,
    creative_fields,
)


def _ad(headline: str, text: str, angle: str = "") -> MetaAdCreative:
    return MetaAdCreative(headline, text, "https://cdn.exemplu.ro/a.jpg", angle)


def _spec(**overrides: object) -> MetaLaunchSpec:
    fields: dict[str, object] = {
        "campaign_name": "Fizio - Lead-uri",
        "objective": CampaignObjective.LEAD_GEN,
        "daily_budget": Decimal("100.00"),
        "pixel_id": "1234567890",
        "custom_event_type": "LEAD",
        "page_id": "9876543210",
        "target_url": "https://exemplu.ro/programare",
        "headline": "Durere de spate de la birou?",
        "primary_text": "Kinetoterapeutul tau te scapa de durerea lombara in 4 sedinte.",
        "image_url": "https://cdn.exemplu.ro/reclama.jpg",
        "country": "RO",
        "call_to_action": "LEARN_MORE",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)  # type: ignore[arg-type]


# --- hook generic -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Hey guys, trebuie sa vezi asta", "Salut! Avem o oferta", "Check this out: ceva nou"],
)
def test_formulele_generice_sunt_recunoscute(text: str) -> None:
    assert is_generic_hook(text)


def test_un_hook_care_numeste_problema_nu_e_generic() -> None:
    assert not is_generic_hook("Durere de spate de la birou? Iata ce functioneaza")


# --- similaritate -----------------------------------------------------------


def test_acelasi_mesaj_cu_alta_imagine_e_acelasi_anunt() -> None:
    ads = [
        _ad("Scapa de durerea de spate", "Kinetoterapie pentru durerea de spate, programeaza azi"),
        _ad("Scapa de durerea de spate", "Kinetoterapie pentru durerea de spate, programeaza acum"),
    ]
    assert similar_pairs(ads)[0][:2] == (0, 1)
    assert any("aproape acelasi lucru" in w for w in portfolio_findings(ads).warnings)


def test_persoane_si_unghiuri_diferite_nu_sunt_semnalate() -> None:
    ads = [
        _ad(
            "Durere de spate de la birou?", "Programatorii pierd ore la birou, te punem pe picioare"
        ),
        _ad(
            "Dupa nastere, spatele nu te mai ajuta",
            "Mame proaspete: recuperare blanda, sedinte scurte",
        ),
    ]
    assert portfolio_findings(ads).warnings == []


def test_acelasi_unghi_declarat_este_semnalat() -> None:
    ads = [
        _ad("Durere de spate de la birou?", "Text unu complet diferit despre ergonomie", "durere"),
        _ad("Nu mai lua pastile", "Alt text despre recuperare fara medicamente", "Durere"),
    ]
    assert any("acelasi unghi" in w for w in portfolio_findings(ads).warnings)


# --- capacitatea bugetului --------------------------------------------------


def test_mai_multe_reclame_decat_hraneste_bugetul() -> None:
    ads = [_ad(f"Titlu {i}", f"Text distinct {i} despre subiectul {i * 7}") for i in range(4)]
    findings = portfolio_findings(ads, max_concurrent_arms=2)
    assert any("hraneste cel mult 2" in w for w in findings.warnings)


def test_o_singura_reclama_la_buget_care_ar_hrani_mai_multe() -> None:
    findings = portfolio_findings([_ad("Titlu", "Text")], max_concurrent_arms=4)
    assert findings.warnings == []
    assert "diversitate" in findings.suggestions[0]


def test_capacitate_necunoscuta_nu_ridica_nimic() -> None:
    assert portfolio_findings([_ad("Titlu", "Text")], max_concurrent_arms=None).suggestions == []


# --- specificatia cu mai multe reclame --------------------------------------


def test_o_singura_reclama_pastreaza_versiunea_si_forma_veche() -> None:
    payload = _spec().to_payload()
    assert payload["launch_spec_version"] == LAUNCH_SPEC_VERSION
    assert "extra_ads" not in payload
    assert MetaLaunchSpec.from_payload(payload).extra_ads == ()


def test_reclamele_in_plus_fac_drumul_dus_intors() -> None:
    spec = _spec(extra_ads=(_ad("Alt titlu", "Alt text", "nastere"),))
    payload = spec.to_payload()
    assert payload["launch_spec_version"] == LAUNCH_SPEC_VERSION_MULTI_AD
    assert MetaLaunchSpec.from_payload(payload) == spec
    assert len(spec.ads) == 2
    assert spec.ads[0].headline == spec.headline


def test_prea_multe_reclame_se_resping() -> None:
    extras = tuple(_ad(f"T{i}", f"X{i}") for i in range(MAX_ADS_PER_LAUNCH))
    with pytest.raises(ValueError, match="maxim"):
        _spec(extra_ads=extras)


def test_reclama_in_plus_cere_imagine_https() -> None:
    with pytest.raises(ValueError, match="https"):
        MetaAdCreative("Titlu", "Text", "http://nesigur.ro/a.jpg")


def test_numele_si_textul_creative_urmeaza_reclama() -> None:
    spec = _spec()
    extra = _ad("Titlu doi", "Text doi")
    story = creative_fields(spec, image_hash="h2", ad=extra, index=1)
    assert story["name"].endswith("Creative 2")
    assert "Titlu doi" in story["object_story_spec"]
    assert ad_fields(spec, adset_id="1", creative_id="2", index=1)["name"].endswith("Ad 2")
    assert creative_fields(spec, image_hash="h")["name"].endswith("- Creative")


def test_rezultatul_listeaza_reclamele_in_plus_doar_cand_exista() -> None:
    base = LaunchResult("c", "s", "h", "cr", "ad1")
    assert "extra_ad_ids" not in base.as_dict()
    more = LaunchResult("c", "s", "h", "cr", "ad1", extra_ad_ids=("ad2", "ad3"))
    assert more.as_dict()["extra_ad_ids"] == "ad2,ad3"
