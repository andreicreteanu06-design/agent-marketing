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
        "/api/v1/seo-geo/analyze", headers=auth_headers, json={}
    )
    assert response.status_code == 422  # domain lipseste (client_reports e optional)


def test_analyze_succeeds_with_domain_only_via_auto_fetch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """client_reports e optional - fixture-ul `client` suprascrie deja
    auto-fetch-ul cu unul fals, fara retea (vezi conftest.py); un domeniu
    singur, fara raport manual, tot produce o analiza valida."""
    response = client.post(
        "/api/v1/seo-geo/analyze",
        headers=auth_headers,
        json={"domain": "exemplu.ro"},
    )
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["seo_score"] <= 100
    assert 0 <= body["geo_score"] <= 100


def test_analyze_rejects_when_no_data_available_at_all(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Fara raport manual SI cu auto-fetch care nu gaseste nimic (domeniu
    inaccesibil, rate-limit etc.) - 422 explicit, nu o analiza construita din
    nimic."""

    async def _empty_fetch(domain: str) -> str:
        return ""

    overrides = client.app.dependency_overrides
    overrides[router_module._get_auto_fetcher] = lambda: _empty_fetch
    try:
        response = client.post(
            "/api/v1/seo-geo/analyze",
            headers=auth_headers,
            json={"domain": "exemplu.ro"},
        )
        assert response.status_code == 422
        assert "Nu am nicio informatie" in response.json()["detail"]
    finally:
        overrides.clear()


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


def test_analyze_combines_manual_and_auto_fetched_reports(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Confirma ca textul auto-preluat chiar ajunge la LLM (nu doar ca raspunsul
    e 200) - MockLLMClient marcheaza schema markup diferit daca "schema" apare
    in text (vezi llm.py); niciunul din cele doua rapoarte, singur, nu contine
    cuvantul - doar combinatia lor."""

    async def _schema_signal_fetch(domain: str) -> str:
        return "Raport auto-preluat: pagina foloseste deja schema markup peste tot."

    overrides = client.app.dependency_overrides
    overrides[router_module._get_auto_fetcher] = lambda: _schema_signal_fetch
    try:
        response = client.post(
            "/api/v1/seo-geo/analyze",
            headers=auth_headers,
            json={"domain": "exemplu.ro", "client_reports": "GSC: 1200 clicuri/luna."},
        )
        assert response.status_code == 200
        issue = response.json()["seo_suggestions"][0]["current_issue"]
        assert "mentioneaza schema markup" in issue
    finally:
        overrides.clear()


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
