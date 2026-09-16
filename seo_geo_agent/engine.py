"""``SeoGeoAnalyzer`` - orchestreaza analiza: cere clientului (mock sau live) un
:class:`~seo_geo_agent.schemas.AnalysisResponse`, cu un retry marginit daca
raspunsul nu respecta schema.
"""

from __future__ import annotations

from seo_geo_agent.errors import AnalysisError
from seo_geo_agent.llm import BaseLLMClient
from seo_geo_agent.schemas import AnalysisRequest, AnalysisResponse

_MAX_ATTEMPTS = 2


class SeoGeoAnalyzer:
    """Genereaza o analiza SEO+GEO, cu un client LLM injectat."""

    def __init__(self, llm_client: BaseLLMClient) -> None:
        self._client = llm_client

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        """Analizeaza ``request``, cu retry pe raspuns invalid.

        ``SetupRequiredError`` (Ollama nu ruleaza/nu are modelul) nu se
        reincearca - e o problema de mediu, nu una care se rezolva singura la
        a doua cerere identica.

        Raises:
            AnalysisError: dupa ``_MAX_ATTEMPTS`` raspunsuri invalide la rand.
            SetupRequiredError: propagata neschimbata de la client.
        """
        last_error: AnalysisError | None = None
        for _ in range(_MAX_ATTEMPTS):
            try:
                return self._client.analyze(request)
            except AnalysisError as exc:
                last_error = exc
        assert last_error is not None  # bucla ruleaza cel putin o data (_MAX_ATTEMPTS >= 1)
        raise last_error
