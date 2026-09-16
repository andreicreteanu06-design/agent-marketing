"""Teste end-to-end pentru POST /api/v1/seo-geo/analyze."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from seo_geo_agent import router as router_module
from seo_geo_agent.errors import AnalysisError, SetupRequiredError
from seo_geo_agent.llm import BaseLLMClient
from seo_geo_agent.schemas import AnalysisRequest, AnalysisResponse

_PAYLOAD = {"domain": "exemplu.ro", "client_reports": "GSC: 1200 clicuri/luna."}


def test_analyze_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/seo-geo/analyze", json=_PAYLOAD)
    assert response.status_code == 401


def test_analyze_rejects_invalid_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/seo-geo/analyze", headers=auth_headers, json={"domain": "exemplu.ro"}
    )
    assert response.status_code == 422  # client_reports lipseste


def test_analyze_returns_valid_response_with_mock_provider(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Implicit (fara SEOGEO_PROVIDER_MODE=live), endpoint-ul foloseste MockLLMClient."""
    response = client.post("/api/v1/seo-geo/analyze", headers=auth_headers, json=_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["seo_score"] <= 100
    assert 0 <= body["geo_score"] <= 100
    assert body["seo_suggestions"]
    assert body["geo_suggestions"]


class _RaisingClient(BaseLLMClient):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        raise self._exc


def _raising_client_factory(exc: Exception) -> Callable[[], BaseLLMClient]:
    def factory() -> BaseLLMClient:
        return _RaisingClient(exc)

    return factory


def test_analyze_maps_setup_required_to_503(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    overrides = client.app.dependency_overrides
    overrides[router_module._build_llm_client] = _raising_client_factory(
        SetupRequiredError("ollama nu ruleaza")
    )
    try:
        response = client.post("/api/v1/seo-geo/analyze", headers=auth_headers, json=_PAYLOAD)
        assert response.status_code == 503
    finally:
        overrides.clear()


def test_analyze_maps_analysis_error_to_502(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    overrides = client.app.dependency_overrides
    overrides[router_module._build_llm_client] = _raising_client_factory(
        AnalysisError("raspuns invalid")
    )
    try:
        response = client.post("/api/v1/seo-geo/analyze", headers=auth_headers, json=_PAYLOAD)
        assert response.status_code == 502
    finally:
        overrides.clear()
