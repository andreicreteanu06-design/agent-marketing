"""Teste pentru SeoGeoAnalyzer - orchestrarea si retry-ul marginit."""

from __future__ import annotations

import pytest

from seo_geo_agent.engine import SeoGeoAnalyzer
from seo_geo_agent.errors import AnalysisError, SetupRequiredError
from seo_geo_agent.llm import BaseLLMClient
from seo_geo_agent.schemas import AnalysisRequest, AnalysisResponse

_REQUEST = AnalysisRequest(domain="exemplu.ro", client_reports="raport minimal")


class _FailNTimesClient(BaseLLMClient):
    """Ridica AnalysisError de ``fail_count`` ori, apoi reuseste."""

    def __init__(self, fail_count: int) -> None:
        self._remaining = fail_count
        self.calls = 0

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise AnalysisError("raspuns invalid simulat")
        return AnalysisResponse(seo_score=50, geo_score=50)


class _AlwaysFailsClient(BaseLLMClient):
    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        raise AnalysisError("mereu invalid")


class _SetupRequiredClient(BaseLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        self.calls += 1
        raise SetupRequiredError("ollama nu ruleaza")


def test_succeeds_on_first_attempt() -> None:
    client = _FailNTimesClient(fail_count=0)
    result = SeoGeoAnalyzer(client).analyze(_REQUEST)
    assert result.seo_score == 50
    assert client.calls == 1


def test_retries_once_then_succeeds() -> None:
    client = _FailNTimesClient(fail_count=1)
    result = SeoGeoAnalyzer(client).analyze(_REQUEST)
    assert result.seo_score == 50
    assert client.calls == 2


def test_raises_after_exhausting_retries() -> None:
    client = _AlwaysFailsClient()
    with pytest.raises(AnalysisError):
        SeoGeoAnalyzer(client).analyze(_REQUEST)


def test_setup_required_error_is_not_retried() -> None:
    """Ollama nefunctional e o problema de mediu - a doua cerere identica nu ajuta."""
    client = _SetupRequiredClient()
    with pytest.raises(SetupRequiredError):
        SeoGeoAnalyzer(client).analyze(_REQUEST)
    assert client.calls == 1
