"""Clientul Hugging Face pentru vocea Reginei - un singur apel HTTP, fara SDK.

Fara ``transformers``/``torch``/``huggingface_hub``: doar ``httpx`` (deja
dependinta a proiectului) catre API-ul de chat compatibil OpenAI.

De ce ``router.huggingface.co`` si nu ``api-inference.huggingface.co/models/...``:
vechiul API "serverless" a fost inlocuit de Inference Providers - gazda veche
raspunde 410 (sau nu mai are DNS). Routerul alege singur furnizorul care
serveste modelul (Featherless, Together, Groq...).

Clientul NU stie nimic despre Regina, directive sau bugete: primeste un prompt
de sistem si unul de utilizator si intoarce text. Ce se trimite si ce se
accepta inapoi decide ``queen_agent.BrandStrategist.generate_cmo_message``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ppc_agent_server.settings import ServerSettings

HF_CHAT_COMPLETIONS_URL = "https://router.huggingface.co/v1/chat/completions"
#: Servit live prin Inference Providers (verificat in septembrie 2026).
#: ``mistralai/Mixtral-8x7B-Instruct-v0.1`` nu mai e servit de niciun furnizor.
DEFAULT_HF_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"

#: Cat din corpul unui raspuns de eroare ajunge in mesaj (si in log-uri).
_ERROR_DETAIL_CHARS = 200


class HuggingFaceError(RuntimeError):
    """Hugging Face nu a intors un text utilizabil (retea, cheie, model, format)."""


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:_ERROR_DETAIL_CHARS]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if error:
            return str(error)[:_ERROR_DETAIL_CHARS]
    return str(body)[:_ERROR_DETAIL_CHARS]


@dataclass(frozen=True, slots=True)
class HuggingFaceChatClient:
    """Chat completion prin Inference Providers - implementeaza ``queen_agent.TextGenerator``."""

    api_key: str
    model: str = DEFAULT_HF_MODEL
    timeout: float = 30.0
    max_tokens: int = 450
    #: Scazuta: vrem formulare, nu creativitate - faptele vin din directiva.
    temperature: float = 0.3
    url: str = HF_CHAT_COMPLETIONS_URL
    transport: httpx.BaseTransport | None = None

    def complete(self, *, system: str, user: str) -> str:
        """Raspunsul modelului la cele doua mesaje.

        Raises:
            HuggingFaceError: orice nu e un raspuns 200 cu text nevid - fara
                cheia in mesaj.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise HuggingFaceError(f"Hugging Face nu a răspuns ({type(exc).__name__})") from exc

        if response.status_code != 200:
            raise HuggingFaceError(
                f"Hugging Face a răspuns {response.status_code}: {_error_detail(response)}"
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise HuggingFaceError("Hugging Face a întors un răspuns neașteptat") from exc
        if not isinstance(content, str) or not content.strip():
            raise HuggingFaceError("Hugging Face a întors un mesaj gol")
        return content.strip()


def hf_client_from_settings(settings: ServerSettings) -> HuggingFaceChatClient | None:
    """Clientul din ``.env`` sau ``None`` cand nu exista cheie (-> mesaj din template)."""
    api_key = settings.huggingface_api_key.strip()
    if not api_key:
        return None
    return HuggingFaceChatClient(
        api_key=api_key, model=settings.huggingface_model.strip() or DEFAULT_HF_MODEL
    )
