"""Clientul Hugging Face: forma cererii, erorile si configurarea din ``.env``.

Fara retea: Hugging Face e un ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ppc_agent_server.services.hf_client import (
    DEFAULT_HF_MODEL,
    HF_CHAT_COMPLETIONS_URL,
    HuggingFaceChatClient,
    HuggingFaceError,
    hf_client_from_settings,
)
from ppc_agent_server.settings import ServerSettings

_KEY = "hf_secret_test_key"


def _client(handler: httpx.MockTransport) -> HuggingFaceChatClient:
    return HuggingFaceChatClient(api_key=_KEY, transport=handler)


def _chat_response(content: object) -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_complete_posts_an_openai_compatible_chat_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_chat_response("  Mesajul CMO.  "))

    text = _client(httpx.MockTransport(handler)).complete(system="rol", user="fapte")

    assert text == "Mesajul CMO."
    [request] = seen
    assert str(request.url) == HF_CHAT_COMPLETIONS_URL
    assert request.url.host == "router.huggingface.co"
    assert request.headers["Authorization"] == f"Bearer {_KEY}"
    body = json.loads(request.content)
    assert body["model"] == DEFAULT_HF_MODEL
    assert body["messages"] == [
        {"role": "system", "content": "rol"},
        {"role": "user", "content": "fapte"},
    ]
    assert body["stream"] is False


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, json={"error": "Invalid credentials"}), "401: Invalid credentials"),
        (
            httpx.Response(400, json={"error": {"message": "Model not supported"}}),
            "400: Model not supported",
        ),
        (httpx.Response(503, text="overloaded"), "503: overloaded"),
        (httpx.Response(200, json={"choices": []}), "neașteptat"),
        (httpx.Response(200, text="nu e json"), "neașteptat"),
        (httpx.Response(200, json=_chat_response("   ")), "gol"),
        (httpx.Response(200, json=_chat_response(None)), "gol"),
    ],
)
def test_unusable_answers_raise_without_leaking_the_key(
    response: httpx.Response, expected: str
) -> None:
    client = _client(httpx.MockTransport(lambda request: response))
    with pytest.raises(HuggingFaceError, match=expected) as excinfo:
        client.complete(system="s", user="u")
    assert _KEY not in str(excinfo.value)


def test_network_errors_become_huggingface_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fara retea", request=request)

    with pytest.raises(HuggingFaceError, match="ConnectError"):
        _client(httpx.MockTransport(handler)).complete(system="s", user="u")


def test_no_key_means_no_client() -> None:
    assert hf_client_from_settings(ServerSettings(huggingface_api_key="")) is None
    assert hf_client_from_settings(ServerSettings(huggingface_api_key="   ")) is None


def test_client_from_settings_uses_the_model_override() -> None:
    default = hf_client_from_settings(ServerSettings(huggingface_api_key=_KEY))
    custom = hf_client_from_settings(
        ServerSettings(huggingface_api_key=_KEY, huggingface_model="Qwen/Qwen2.5-7B-Instruct")
    )
    assert default is not None and default.model == DEFAULT_HF_MODEL
    assert custom is not None and custom.model == "Qwen/Qwen2.5-7B-Instruct"
