"""Teste pentru MockLLMClient si LiveLLMClient (Ollama), fara retea reala.

LiveLLMClient foloseste ``httpx.MockTransport`` pentru a simula serverul Ollama -
acelasi pattern ca ``tests/test_llm_live.py`` (ppc_agent), niciun apel de retea
nu paraseste procesul de test.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from seo_geo_agent.errors import AnalysisError, SetupRequiredError
from seo_geo_agent.llm import LiveLLMClient, MockLLMClient
from seo_geo_agent.schemas import AnalysisRequest, AnalysisResponse

_REQUEST = AnalysisRequest(
    domain="exemplu.ro",
    client_reports="GSC: 1200 clicuri/luna, 40 de pagini indexate.",
)

_VALID_RESPONSE = {
    "seo_score": 55,
    "geo_score": 30,
    "seo_suggestions": [
        {
            "category": "Schema Markup",
            "current_issue": "lipseste",
            "exact_fix": "<script>...</script>",
        }
    ],
    "geo_suggestions": [],
}


def test_mock_client_is_deterministic() -> None:
    first = MockLLMClient().analyze(_REQUEST)
    second = MockLLMClient().analyze(_REQUEST)
    assert first == second


def test_mock_client_returns_valid_schema() -> None:
    response = MockLLMClient().analyze(_REQUEST)
    assert isinstance(response, AnalysisResponse)
    assert 0 <= response.seo_score <= 100
    assert 0 <= response.geo_score <= 100
    assert response.seo_suggestions
    assert response.geo_suggestions


def test_mock_client_detects_schema_signal_in_report() -> None:
    without_signal = MockLLMClient().analyze(_REQUEST)
    with_signal = MockLLMClient().analyze(
        AnalysisRequest(
            domain="exemplu.ro", client_reports="Am implementat deja schema JSON-LD peste tot."
        )
    )
    assert with_signal.seo_score > without_signal.seo_score


def _ok_transport(content: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}, "done": True})

    return httpx.MockTransport(handler)


def _ok_transport_raw(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": content}, "done": True})

    return httpx.MockTransport(handler)


def _raising_transport(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


def _not_found_transport(models: list[str] | None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            return httpx.Response(404, json={"error": "model not found"})
        if models is None:
            return httpx.Response(500, json={"error": "tags indisponibil"})
        return httpx.Response(200, json={"models": [{"name": m} for m in models]})

    return httpx.MockTransport(handler)


def test_live_client_parses_valid_response() -> None:
    client = LiveLLMClient("llama3", transport=_ok_transport(_VALID_RESPONSE))
    response = client.analyze(_REQUEST)
    assert response.seo_score == 55
    assert response.seo_suggestions[0].category == "Schema Markup"


def test_live_client_strips_ollama_prefix() -> None:
    client = LiveLLMClient("ollama/llama3", transport=_ok_transport(_VALID_RESPONSE))
    assert client.model == "llama3"


def test_live_client_connect_error_raises_setup_required() -> None:
    client = LiveLLMClient("llama3", transport=_raising_transport(httpx.ConnectError("refuzat")))
    with pytest.raises(SetupRequiredError):
        client.analyze(_REQUEST)


def test_live_client_timeout_raises_setup_required() -> None:
    transport = _raising_transport(httpx.TimeoutException("timeout"))
    client = LiveLLMClient("llama3", transport=transport)
    with pytest.raises(SetupRequiredError):
        client.analyze(_REQUEST)


def test_live_client_missing_model_raises_setup_required_with_hint() -> None:
    client = LiveLLMClient("llama3", transport=_not_found_transport(["qwen2.5", "mistral"]))
    with pytest.raises(SetupRequiredError, match=re.escape("qwen2.5")):
        client.analyze(_REQUEST)


def test_live_client_invalid_json_raises_analysis_error() -> None:
    client = LiveLLMClient("llama3", transport=_ok_transport_raw("nu e json"))
    with pytest.raises(AnalysisError):
        client.analyze(_REQUEST)


def test_live_client_schema_mismatch_raises_analysis_error() -> None:
    client = LiveLLMClient("llama3", transport=_ok_transport({"seo_score": "nu e numar"}))
    with pytest.raises(AnalysisError):
        client.analyze(_REQUEST)
