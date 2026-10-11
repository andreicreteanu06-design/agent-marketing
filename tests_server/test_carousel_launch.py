"""Reclamele carusel: specificatia, creative-ul Meta, lansarea si cererea."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ppc_agent.decision.andromeda_rules import portfolio_findings
from ppc_agent.providers.meta_campaign import (
    CarouselCard,
    MetaAdCreative,
    MetaLaunchSpec,
    creative_fields,
)
from seo_geo_agent.audit import url_policy
from tests_server.test_campaign_launch import _request, launcher  # noqa: F401
from tests_server.test_campaign_launch_execution import _Meta, _spec


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", public)


def _cards(count: int) -> tuple[CarouselCard, ...]:
    return tuple(
        CarouselCard(f"Pasul {i + 1}", f"https://cdn.exemplu.ro/card{i + 1}.jpg")
        for i in range(count)
    )


# --- specificatia --------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 11])
def test_un_carusel_are_intre_2_si_10_carduri(count: int) -> None:
    with pytest.raises(ValueError, match="intre 2 si 10 carduri"):
        _spec(carousel=_cards(count))


def test_o_reclama_nu_poate_fi_si_video_si_carusel() -> None:
    with pytest.raises(ValueError, match="fie video, fie carusel"):
        _spec(carousel=_cards(3), video_url="https://cdn.exemplu.ro/clip.mp4")


def test_caruselul_face_drumul_dus_intors_si_are_formatul_lui() -> None:
    extra = MetaAdCreative(
        "Alt titlu", "Alt text", "https://cdn.exemplu.ro/b.jpg", carousel=_cards(2)
    )
    spec = _spec(carousel=_cards(3), extra_ads=(extra,))

    assert MetaLaunchSpec.from_payload(spec.to_payload()) == spec
    assert [ad.format for ad in spec.ads] == ["carousel", "carousel"]
    assert spec.ads[0].upload_images == [card.image_url for card in _cards(3)]


def test_creative_ul_carusel_are_cate_un_card_cu_imaginea_lui() -> None:
    spec = _spec(carousel=_cards(3))
    story = json.loads(
        creative_fields(spec, image_hash="h1", card_hashes=("h1", "h2", "h3"))["object_story_spec"]
    )
    link = story["link_data"]
    assert [card["image_hash"] for card in link["child_attachments"]] == ["h1", "h2", "h3"]
    assert [card["name"] for card in link["child_attachments"]] == ["Pasul 1", "Pasul 2", "Pasul 3"]
    assert link["multi_share_optimized"] is True
    assert "image_hash" not in link  # caruselul nu are o imagine principala


def test_un_carusel_fara_video_primeste_sugestia_de_video() -> None:
    carousel = MetaAdCreative(
        "T", "Text despre pret", "https://cdn.exemplu.ro/a.jpg", carousel=_cards(2)
    )
    image = MetaAdCreative("Altceva", "Alt text despre garantie", "https://cdn.exemplu.ro/b.jpg")
    assert any("video" in s for s in portfolio_findings([carousel, image]).suggestions)


# --- lansarea ---------------------------------------------------------------------------


def test_lansarea_urca_fiecare_card_si_creeaza_un_singur_creative() -> None:
    meta = _Meta()
    meta.launch(_spec(carousel=_cards(3)))

    methods = [method for method, _, _ in meta.calls]
    assert methods[:3] == ["GET", "GET", "GET"]  # cele 3 carduri, inainte de orice POST
    assert meta.meta_posts == [
        "campaigns",
        "adsets",
        "adimages",
        "adimages",
        "adimages",
        "adcreatives",
        "ads",
    ]
    story = json.loads(meta.body_of("adcreatives")["object_story_spec"])
    assert len(story["link_data"]["child_attachments"]) == 3


# --- cererea ---------------------------------------------------------------------------


def test_cererea_cu_carusel_ajunge_in_propunere(
    launcher: tuple[TestClient, dict[str, str], int],  # noqa: F811
) -> None:
    client, headers, _ = launcher
    cards: list[dict[str, Any]] = [
        {"headline": f"Pasul {i}", "image_url": f"https://cdn.exemplu.ro/c{i}.jpg"}
        for i in range(1, 4)
    ]
    response = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request(carousel=cards)
    )

    assert response.status_code == 201, response.text
    after = response.json()["after"]
    assert [card["headline"] for card in after["carousel"]] == ["Pasul 1", "Pasul 2", "Pasul 3"]
    orders = response.json()["before"]["campaign_orders"]
    assert orders["ads"][0]["format"] == "carousel"
    assert Decimal(after["daily_budget"]) == Decimal("25.00")
