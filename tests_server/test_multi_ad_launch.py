"""Lansarea cu mai multe reclame in acelasi ad set (post-Andromeda)."""

from __future__ import annotations

from typing import Any

import pytest

from ppc_agent.providers.meta_campaign import MetaAdCreative
from seo_geo_agent.audit import url_policy
from tests_server.test_campaign_launch_execution import _Meta, _spec


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", public)


def _three_ads() -> dict[str, Any]:
    return {
        "extra_ads": (
            MetaAdCreative("Alt titlu", "Alt text", "https://cdn.exemplu.ro/b.jpg", "unghi b"),
            MetaAdCreative("Al treilea", "Text trei", "https://cdn.exemplu.ro/c.jpg", "unghi c"),
        )
    }


def test_un_ad_set_si_cate_un_creative_si_anunt_pentru_fiecare() -> None:
    meta = _Meta()
    result = meta.launch(_spec(**_three_ads()))

    per_ad = ["adimages", "adcreatives", "ads"]
    assert meta.meta_posts == ["campaigns", "adsets", *per_ad, *per_ad, *per_ad]
    assert len(result.extra_ad_ids) == 2


def test_toate_imaginile_se_descarca_inainte_de_orice_apel_meta() -> None:
    meta = _Meta()
    meta.launch(_spec(**_three_ads()))

    methods = [method for method, _, _ in meta.calls]
    assert methods[:3] == ["GET", "GET", "GET"]
    assert methods.index("POST") == 3


def test_toate_anunturile_pornesc_oprite_si_in_acelasi_ad_set() -> None:
    meta = _Meta()
    meta.launch(_spec(**_three_ads()))

    ad_bodies = [
        body for method, url, body in meta.calls if method == "POST" and url.endswith("/ads")
    ]
    assert len(ad_bodies) == 3
    assert {body["status"] for body in ad_bodies} == {"PAUSED"}
    assert {body["adset_id"] for body in ad_bodies} == {"adset_456"}
    assert [body["name"].rsplit(" - ", 1)[1] for body in ad_bodies] == ["Ad", "Ad 2", "Ad 3"]


def test_o_reclama_picata_sterge_toata_campania() -> None:
    meta = _Meta(fail_on="/ads")
    with pytest.raises(Exception, match="ad"):
        meta.launch(_spec(**_three_ads()))
    assert meta.deleted == ["camp_123"]
