"""Lansarea unei reclame video: verificarea URL-ului, urcarea, procesarea, creative-ul."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from ppc_agent.errors import CampaignLaunchError
from ppc_agent.providers.live.meta import LiveMetaMarketingProvider
from seo_geo_agent.audit import url_policy
from tests_server.test_campaign_launch_execution import _Meta, _spec

_VIDEO = "https://cdn.exemplu.ro/clip.mp4"


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", public)


class _VideoMeta(_Meta):
    """Graph API cu ``/advideos`` si starea video-ului, plus serverul care tine clipul."""

    def __init__(
        self,
        *,
        statuses: tuple[str, ...] = ("ready",),
        video_type: str = "video/mp4",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._statuses = list(statuses)
        self._video_type = video_type

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and url == _VIDEO:
            self.calls.append(("GET", url, {}))
            return httpx.Response(200, content=b"", headers={"content-type": self._video_type})
        if request.method == "GET" and "/vid_1" in url:
            self.calls.append(("GET", url, {}))
            status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
            return httpx.Response(200, json={"id": "vid_1", "status": {"video_status": status}})
        if request.method == "POST" and url.endswith("/advideos"):
            self.calls.append(("POST", url, dict(parse_qsl(request.content.decode()))))
            return httpx.Response(200, json={"id": "vid_1"})
        return super().handler(request)

    def provider(self, currency: str = "RON") -> LiveMetaMarketingProvider:
        return LiveMetaMarketingProvider(
            access_token="token-123",
            currency=currency,
            transport=httpx.MockTransport(self.handler),
            video_poll_seconds=0,
            video_poll_attempts=3,
        )


def test_video_ul_se_verifica_se_urca_se_asteapta_si_devine_creative_video() -> None:
    meta = _VideoMeta(statuses=("processing", "ready"))
    meta.launch(_spec(video_url=_VIDEO))

    assert meta.meta_posts == ["campaigns", "adsets", "adimages", "advideos", "adcreatives", "ads"]
    first_post = next(i for i, (method, _, _) in enumerate(meta.calls) if method == "POST")
    assert (meta.calls[1][0], meta.calls[1][1]) == ("GET", _VIDEO)  # inainte de orice POST
    assert first_post == 2
    assert meta.body_of("advideos")["file_url"] == _VIDEO
    story = json.loads(meta.body_of("adcreatives")["object_story_spec"])
    assert story["video_data"]["video_id"] == "vid_1"
    assert story["video_data"]["image_hash"] == "hash_abc"  # coperta


def test_un_url_care_nu_e_video_nu_creeaza_nimic() -> None:
    meta = _VideoMeta(video_type="text/html")
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch(_spec(video_url=_VIDEO))

    assert caught.value.stage == "image_download"
    assert meta.meta_posts == []


def test_un_video_pe_care_meta_nu_il_poate_procesa_sterge_campania() -> None:
    meta = _VideoMeta(statuses=("error",))
    with pytest.raises(CampaignLaunchError) as caught:
        meta.launch(_spec(video_url=_VIDEO))

    assert caught.value.stage == "video_processing"
    assert meta.deleted == ["camp_123"]


def test_un_video_care_nu_se_termina_de_procesat_sterge_campania() -> None:
    meta = _VideoMeta(statuses=("processing",))
    with pytest.raises(CampaignLaunchError, match="nu s-a procesat"):
        meta.launch(_spec(video_url=_VIDEO))
    assert meta.deleted == ["camp_123"]
