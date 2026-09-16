"""``POST /api/v1/seo-geo/analyze`` - singurul endpoint al acestui agent."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from seo_geo_agent.auth import get_current_client_id
from seo_geo_agent.engine import SeoGeoAnalyzer
from seo_geo_agent.llm import BaseLLMClient, LiveLLMClient, MockLLMClient
from seo_geo_agent.schemas import AnalysisRequest, AnalysisResponse
from seo_geo_agent.settings import ProviderMode, get_seo_geo_settings

router = APIRouter(prefix="/api/v1/seo-geo", tags=["seo-geo"])


def _build_llm_client() -> BaseLLMClient:
    settings = get_seo_geo_settings()
    if settings.provider_mode is ProviderMode.MOCK:
        return MockLLMClient()
    num_gpu = int(settings.llm_num_gpu) if settings.llm_num_gpu.strip() else None
    return LiveLLMClient(settings.llm_model, settings.llm_endpoint, num_gpu=num_gpu)


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(
    payload: AnalysisRequest,
    llm_client: Annotated[BaseLLMClient, Depends(_build_llm_client)],
    _client_id: Annotated[int, Depends(get_current_client_id)],
) -> AnalysisResponse:
    """Analizeaza un domeniu + rapoartele clientului; returneaza scoruri + sugestii.

    Necesita autentificare (acelasi token de client folosit pe restul site-ului) -
    e un feature premium, nu un endpoint public. ``llm_client`` e o dependinta
    (nu construit direct in corp) ca testele sa poata injecta un client fals
    prin ``app.dependency_overrides[_build_llm_client]``.
    """
    return SeoGeoAnalyzer(llm_client).analyze(payload)
