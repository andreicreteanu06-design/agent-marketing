"""Optimizarea fortata pe conversia CAPI si reclamele video in specificatia de lansare."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.creative.concepts import CONCEPT_TEMPLATES, CONCEPTS, concept_brief
from ppc_agent.decision.andromeda_rules import portfolio_findings
from ppc_agent.providers.meta_campaign import (
    CAPI_EVENT_TYPES,
    LAUNCH_SPEC_VERSION_MULTI_AD,
    MetaAdCreative,
    MetaLaunchSpec,
    adset_fields,
    creative_fields,
    require_conversion_optimization,
    video_fields,
)


def _spec(**overrides: object) -> MetaLaunchSpec:
    fields: dict[str, object] = {
        "campaign_name": "Service Auto - Lead-uri",
        "objective": CampaignObjective.LEAD_GEN,
        "daily_budget": Decimal("50.00"),
        "pixel_id": "1234567890",
        "custom_event_type": "LEAD",
        "page_id": "9876543210",
        "target_url": "https://exemplu.ro/programare",
        "headline": "Cutia automata reparata pana vineri",
        "primary_text": "Diagnoza gratuita, pret fix scris dinainte.",
        "image_url": "https://cdn.exemplu.ro/coperta.jpg",
        "country": "RO",
        "call_to_action": "LEARN_MORE",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)  # type: ignore[arg-type]


# --- optimizarea pe conversia trimisa prin CAPI -------------------------------


@pytest.mark.parametrize("event", sorted(CAPI_EVENT_TYPES))
def test_evenimentele_trimise_prin_capi_sunt_acceptate(event: str) -> None:
    assert _spec(custom_event_type=event).custom_event_type == event


@pytest.mark.parametrize("event", ["COMPLETE_REGISTRATION", "CONTENT_VIEW", "ADD_TO_CART"])
def test_un_eveniment_pe_care_capi_nu_il_trimite_e_refuzat(event: str) -> None:
    with pytest.raises(ValueError, match="CAPI"):
        _spec(custom_event_type=event)


def test_ad_set_ul_optimizeaza_pe_conversie_cu_pixelul_si_evenimentul() -> None:
    fields = adset_fields(_spec(), campaign_id="c1", daily_budget_minor=5000)
    assert fields["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert json.loads(fields["promoted_object"]) == {
        "pixel_id": "1234567890",
        "custom_event_type": "LEAD",
    }


@pytest.mark.parametrize("goal", ["LINK_CLICKS", "LANDING_PAGE_VIEWS", "IMPRESSIONS", "REACH"])
def test_click_urile_si_vizualizarile_de_pagina_nu_pleaca_la_meta(goal: str) -> None:
    fields = adset_fields(_spec(), campaign_id="c1", daily_budget_minor=5000)
    with pytest.raises(ValueError, match="OFFSITE_CONVERSIONS"):
        require_conversion_optimization({**fields, "optimization_goal": goal})


def test_fara_pixel_ad_set_ul_nu_pleaca() -> None:
    fields = adset_fields(_spec(), campaign_id="c1", daily_budget_minor=5000)
    with pytest.raises(ValueError, match="pixel"):
        require_conversion_optimization(
            {**fields, "promoted_object": json.dumps({"custom_event_type": "LEAD"})}
        )


# --- reclame video ------------------------------------------------------------


def test_reclama_video_cere_url_https() -> None:
    with pytest.raises(ValueError, match="video_url"):
        _spec(video_url="http://nesigur.ro/clip.mp4")


def test_video_si_conceptul_fac_drumul_dus_intors() -> None:
    extra = MetaAdCreative(
        "Inainte si dupa",
        "Cutia care smucea, acum lina.",
        "https://cdn.exemplu.ro/b.jpg",
        video_url="https://cdn.exemplu.ro/b.mp4",
        concept_template="before_after",
    )
    spec = _spec(
        video_url="https://cdn.exemplu.ro/a.mp4",
        concept_template="founder_story",
        extra_ads=(extra,),
    )
    payload = spec.to_payload()

    assert payload["launch_spec_version"] == LAUNCH_SPEC_VERSION_MULTI_AD
    assert MetaLaunchSpec.from_payload(payload) == spec
    assert [ad.format for ad in spec.ads] == ["video", "video"]
    assert spec.ads[0].media_url == "https://cdn.exemplu.ro/a.mp4"


def test_un_sablon_necunoscut_e_refuzat() -> None:
    with pytest.raises(ValueError, match="sablon de concept"):
        _spec(concept_template="meme")


def test_creative_ul_video_are_video_data_cu_coperta_si_link_in_cta() -> None:
    spec = _spec(video_url="https://cdn.exemplu.ro/a.mp4")
    story = json.loads(
        creative_fields(spec, image_hash="h_cover", video_id="vid_1")["object_story_spec"]
    )
    assert "link_data" not in story
    video = story["video_data"]
    assert (video["video_id"], video["image_hash"]) == ("vid_1", "h_cover")
    assert video["call_to_action"]["value"]["link"] == "https://exemplu.ro/programare"
    assert video_fields(spec, spec.ads[0])["file_url"] == "https://cdn.exemplu.ro/a.mp4"


def test_doar_imagini_primesc_sugestia_de_video() -> None:
    images = [
        MetaAdCreative("Titlu unu", "Text despre garantie", "https://cdn.exemplu.ro/a.jpg"),
        MetaAdCreative("Alt titlu", "Alt text despre pret fix", "https://cdn.exemplu.ro/b.jpg"),
    ]
    assert any("video" in s for s in portfolio_findings(images).suggestions)
    mixed = [
        images[0],
        MetaAdCreative(
            "Alt titlu",
            "Alt text despre pret fix",
            "https://cdn.exemplu.ro/b.jpg",
            video_url="https://cdn.exemplu.ro/b.mp4",
        ),
    ]
    assert not any("video" in s for s in portfolio_findings(mixed).suggestions)


# --- catalogul de concepte --------------------------------------------------------


def test_fiecare_sablon_are_pasi_pentru_text_imagine_si_video() -> None:
    for key in CONCEPT_TEMPLATES:
        spec = CONCEPTS[key]  # type: ignore[index]
        assert spec.copy_beats and spec.image_cues and spec.video_beats and spec.avoid


def test_copywriterul_primeste_pasii_si_ce_sa_evite() -> None:
    brief = concept_brief("founder_story")
    assert brief["template"] == "founder_story"
    assert brief["label"] == "Povestea fondatorului"
    assert isinstance(brief["copy_beats"], list) and brief["copy_beats"]
