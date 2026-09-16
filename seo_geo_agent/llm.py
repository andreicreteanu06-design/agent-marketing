"""Clienti care produc un :class:`~seo_geo_agent.schemas.AnalysisResponse` dintr-un
:class:`~seo_geo_agent.schemas.AnalysisRequest`, decuplati prin injectie de dependenta.

- :class:`BaseLLMClient` — interfata; :func:`~seo_geo_agent.engine.analyze` primeste
  un client prin parametru.
- :class:`MockLLMClient` — determinist, fara retea; suficient pentru dezvoltare/teste
  fara Ollama pornit.
- :class:`LiveLLMClient` — client real pentru un model Ollama local (gratuit, datele
  nu parasesc masina). Loopback pur, acelasi pattern ca
  ``ppc_agent.copywriter.llm.LiveLLMClient``, implementat independent (agent separat,
  vezi ``__init__.py``).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from seo_geo_agent.errors import AnalysisError, SetupRequiredError
from seo_geo_agent.prompts import SYSTEM_PROMPT, build_user_prompt
from seo_geo_agent.schemas import ActionableSuggestion, AnalysisRequest, AnalysisResponse

_DEFAULT_ENDPOINT = "http://localhost:11434"
_DEFAULT_TIMEOUT = 90.0
_OLLAMA_PREFIX = "ollama/"


class BaseLLMClient(ABC):
    """Interfata unui client care produce un :class:`AnalysisResponse` dintr-o cerere."""

    @abstractmethod
    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        """Analizeaza ``request`` si returneaza un raspuns complet, validat."""


def _stable_score(seed: str, low: int, high: int) -> int:
    """Scor determinist in ``[low, high]`` din hash-ul lui ``seed``."""
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return low + int(digest[:8], 16) % max(1, high - low + 1)


_GEO_SIGNAL_TERMS = ("chatgpt", "perplexity", "ai overview", "geo")


class MockLLMClient(BaseLLMClient):
    """Analiza determinista, fara retea - pentru dezvoltare/teste fara Ollama pornit.

    Nu simuleaza inteligenta reala: citeste cateva semnale textuale simple din
    ``client_reports`` (prezenta cuvintelor "schema"/"json-ld", lungimea raportului)
    ca scorurile sa nu fie complet arbitrare, dar sugestiile raman fixe pe categorie.
    """

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        reports_lower = request.client_reports.lower()
        has_schema_signal = "schema" in reports_lower or "json-ld" in reports_lower
        has_geo_signal = any(term in reports_lower for term in _GEO_SIGNAL_TERMS)

        seo_score = _stable_score(f"seo:{request.domain}", 35, 75)
        seo_score += 10 if has_schema_signal else 0
        geo_score = _stable_score(f"geo:{request.domain}", 20, 60)
        geo_score += 15 if has_geo_signal else 0

        if has_schema_signal:
            schema_issue = (
                f"Raportul pentru {request.domain} mentioneaza schema markup - "
                "verifica acoperirea pe toate tipurile de pagina."
            )
        else:
            schema_issue = (
                f"Nu am gasit un marker explicit de JSON-LD in raportul pentru {request.domain}."
            )

        return AnalysisResponse(
            seo_score=min(seo_score, 100),
            geo_score=min(geo_score, 100),
            seo_suggestions=[
                ActionableSuggestion(
                    category="Schema Markup",
                    current_issue=schema_issue,
                    exact_fix=(
                        '<script type="application/ld+json">\n'
                        "{\n"
                        '  "@context": "https://schema.org",\n'
                        '  "@type": "Organization",\n'
                        f'  "name": "{request.domain}",\n'
                        '  "url": "https://' + request.domain + '"\n'
                        "}\n"
                        "</script>"
                    ),
                ),
                ActionableSuggestion(
                    category="Meta Tags",
                    current_issue="Title/meta description neconfirmate ca optimizate in raport.",
                    exact_fix=f"<title>{request.domain} | Beneficiul principal</title>",
                ),
            ],
            geo_suggestions=[
                ActionableSuggestion(
                    category="Entity Salience",
                    current_issue=(
                        f"Nu exista semnal in raport despre cat de des e mentionat brandul "
                        f"{request.domain} in context."
                    ),
                    exact_fix=(
                        "Repeta numele brandului explicit in primele doua propozitii ale "
                        "fiecarei sectiuni, in loc de pronume."
                    ),
                ),
                ActionableSuggestion(
                    category="Citability",
                    current_issue=(
                        "Continutul nu pare structurat intrebare-raspuns "
                        "(util pentru citare de catre modele AI)."
                    ),
                    exact_fix=(
                        "Adauga o sectiune FAQ cu intrebari exacte pe care clientii le pun, "
                        "fiecare raspuns intr-un singur paragraf auto-continut (3-4 propozitii)."
                    ),
                ),
            ],
        )


def _normalize_model_tag(model: str) -> str:
    """Elimina prefixul stil-LiteLLM ``ollama/`` - API-ul Ollama vrea doar tag-ul."""
    if model.lower().startswith(_OLLAMA_PREFIX):
        return model[len(_OLLAMA_PREFIX) :]
    return model


def _list_local_models(endpoint: str, transport: httpx.BaseTransport | None) -> list[str]:
    """Cele mai bune eforturi: modelele deja descarcate, pentru mesaje de eroare utile."""
    try:
        with httpx.Client(transport=transport, timeout=5.0) as client:
            response = client.get(f"{endpoint}/api/tags")
            response.raise_for_status()
            data = response.json()
        return [name for item in data.get("models", []) if (name := item.get("name"))]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


class LiveLLMClient(BaseLLMClient):
    """Client real pentru un model Ollama local (``/api/chat``, implicit ``:11434``).

    Nu e nevoie de cheie API si niciun text nu paraseste masina - e loopback pur.
    Testele injecteaza un ``transport`` fals (``httpx.MockTransport``), deci suita
    ramane fara retea reala.
    """

    def __init__(
        self,
        model: str = "neconfigurat",
        endpoint: str = "",
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        num_gpu: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = _normalize_model_tag(model)
        self._endpoint = (endpoint or _DEFAULT_ENDPOINT).rstrip("/")
        self._timeout = timeout
        self._num_gpu = num_gpu
        self._transport = transport

    @property
    def model(self) -> str:
        """Tag-ul de model Ollama folosit (fara prefixul ``ollama/``)."""
        return self._model

    @property
    def endpoint(self) -> str:
        """Adresa serverului Ollama (implicit ``http://localhost:11434``)."""
        return self._endpoint

    def _call_ollama_chat(self, system_prompt: str, user_prompt: str) -> Any:
        """Trimite system+user prompt catre Ollama; returneaza continutul JSON parsat.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            AnalysisError: Serverul a raspuns, dar cu eroare HTTP sau raspuns intrerupt.
        """
        options: dict[str, Any] = {"temperature": 0.4}
        if self._num_gpu is not None:
            options["num_gpu"] = self._num_gpu
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": options,
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(f"{self._endpoint}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(
                f"Ollama nu raspunde la {self._endpoint}. Porneste-l cu 'ollama serve' "
                "sau corecteaza SEOGEO_LLM_ENDPOINT in .env."
            ) from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Ollama nu a raspuns in {self._timeout:.0f}s (modelul '{self._model}' "
                "poate fi prea mare pentru hardware-ul disponibil - incearca unul mai mic)."
            ) from exc

        if response.status_code == 404:
            available = _list_local_models(self._endpoint, self._transport)
            hint = (
                f" Modele instalate local: {', '.join(available)}."
                if available
                else " Niciun model instalat local inca."
            )
            raise SetupRequiredError(
                f"Modelul '{self._model}' nu e descarcat in Ollama.{hint} "
                f"Descarca-l cu: ollama pull {self._model}"
            )
        if response.status_code >= 400:
            raise AnalysisError(
                f"Ollama a raspuns cu eroarea {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if not data.get("done", True):
            raise AnalysisError(
                f"Ollama a intrerupt generarea pentru '{self._model}' inainte de a termina "
                "raspunsul."
            )
        content = data["message"]["content"]
        return json.loads(content)

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        """Cere modelului Ollama o analiza SEO+GEO; parseaza JSON-ul returnat.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            AnalysisError: Serverul a raspuns, dar continutul nu e JSON valid cu
                schema :class:`~seo_geo_agent.schemas.AnalysisResponse`.
        """
        try:
            parsed = self._call_ollama_chat(SYSTEM_PROMPT, build_user_prompt(request))
            return AnalysisResponse.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise AnalysisError(
                f"Raspunsul Ollama nu respecta schema AnalysisResponse: {exc}"
            ) from exc
