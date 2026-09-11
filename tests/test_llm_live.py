"""Teste deterministe pentru LiveLLMClient (Ollama), fara retea reala.

Foloseste ``httpx.MockTransport`` pentru a simula serverul Ollama — niciun apel
de retea nu paraseste procesul de test, la fel ca restul suitei.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ppc_agent.config import AppConfig, ProviderMode, Settings
from ppc_agent.copywriter.engine import AdCopyGenerator, build_system_prompt
from ppc_agent.copywriter.llm import LiveLLMClient
from ppc_agent.copywriter.models import (
    DESCRIPTION_LIMIT,
    HEADLINE_LIMIT,
    CopySpec,
    char_count,
)
from ppc_agent.copywriter.swipe import default_swipe_path, load_swipe_file, retrieve_framework
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.errors import CopywriterError, SetupRequiredError

_USP = "Emite facturi in 30 de secunde, cu e-Factura inclusa"


def _spec(tighten: int = 0) -> CopySpec:
    framework = retrieve_framework(load_swipe_file(default_swipe_path()), "fomo")
    system_prompt = build_system_prompt(framework, HEADLINE_LIMIT, DESCRIPTION_LIMIT)
    return CopySpec(
        product_usp=_USP,
        target_keyword="program facturare",
        emotion_trigger="fomo",
        framework=framework,
        system_prompt=system_prompt,
        tighten=tighten,
    )


def _ok_transport(content: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    return httpx.MockTransport(handler)


def _capturing_transport(
    content: dict[str, str], sink: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sink.append(request)
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

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


def _fixed_status_transport(status_code: int, text: str = "eroare") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return httpx.MockTransport(handler)


def _raw_content_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": content}})

    return httpx.MockTransport(handler)


_VALID_AD = {
    "headline_1": "Program facturare",
    "headline_2": "Pretul creste luni",
    "description": "Emite facturi in 30 de secunde, cu e-Factura inclusa azi.",
}


def test_generate_parses_valid_json_content() -> None:
    client = LiveLLMClient(model="llama3", transport=_ok_transport(_VALID_AD))
    ad = client.generate(_spec())
    assert ad.headline_1 == _VALID_AD["headline_1"]
    assert ad.headline_2 == _VALID_AD["headline_2"]
    assert ad.description == _VALID_AD["description"]


def test_model_tag_strips_ollama_prefix_in_request_payload() -> None:
    captured: list[httpx.Request] = []
    client = LiveLLMClient(
        model="ollama/llama3", transport=_capturing_transport(_VALID_AD, captured)
    )
    client.generate(_spec())
    body = json.loads(captured[0].content)
    assert body["model"] == "llama3"


def test_model_tag_without_prefix_is_used_as_is() -> None:
    client = LiveLLMClient(model="qwen2.5", transport=_ok_transport(_VALID_AD))
    assert client.model == "qwen2.5"


def test_default_endpoint_when_blank() -> None:
    client = LiveLLMClient(model="llama3", endpoint="", transport=_ok_transport(_VALID_AD))
    assert client.endpoint == "http://localhost:11434"


def test_custom_endpoint_strips_trailing_slash() -> None:
    client = LiveLLMClient(
        model="llama3", endpoint="http://192.168.1.50:11434/", transport=_ok_transport(_VALID_AD)
    )
    assert client.endpoint == "http://192.168.1.50:11434"


def test_request_carries_system_prompt_and_keyword() -> None:
    captured: list[httpx.Request] = []
    client = LiveLLMClient(model="llama3", transport=_capturing_transport(_VALID_AD, captured))
    spec = _spec()
    client.generate(spec)
    body = json.loads(captured[0].content)
    messages = body["messages"]
    assert messages[0]["content"] == spec.system_prompt
    assert "program facturare" in messages[1]["content"]
    assert _USP in messages[1]["content"]


def test_tighten_adds_concise_instruction_to_user_prompt() -> None:
    captured: list[httpx.Request] = []
    client = LiveLLMClient(model="llama3", transport=_capturing_transport(_VALID_AD, captured))
    client.generate(_spec(tighten=1))
    body = json.loads(captured[0].content)
    assert "mai concis" in body["messages"][1]["content"]


def test_connection_error_raises_setup_required() -> None:
    client = LiveLLMClient(
        model="llama3", transport=_raising_transport(httpx.ConnectError("refuzat"))
    )
    with pytest.raises(SetupRequiredError, match="ollama serve"):
        client.generate(_spec())


def test_timeout_raises_setup_required() -> None:
    client = LiveLLMClient(
        model="llama3", transport=_raising_transport(httpx.TimeoutException("prea lent"))
    )
    with pytest.raises(SetupRequiredError, match="hardware"):
        client.generate(_spec())


def test_model_not_found_lists_local_models_in_message() -> None:
    client = LiveLLMClient(
        model="llama3", transport=_not_found_transport(["mistral:latest", "qwen2.5:7b"])
    )
    with pytest.raises(SetupRequiredError) as excinfo:
        client.generate(_spec())
    assert "mistral:latest" in str(excinfo.value)
    assert "ollama pull llama3" in str(excinfo.value)


def test_model_not_found_without_any_local_models_still_raises_clearly() -> None:
    client = LiveLLMClient(model="llama3", transport=_not_found_transport(None))
    with pytest.raises(SetupRequiredError, match="Niciun model instalat local"):
        client.generate(_spec())


def test_server_error_raises_copywriter_error() -> None:
    client = LiveLLMClient(
        model="llama3", transport=_fixed_status_transport(500, "internal error")
    )
    with pytest.raises(CopywriterError):
        client.generate(_spec())


def test_malformed_json_content_raises_copywriter_error() -> None:
    client = LiveLLMClient(model="llama3", transport=_raw_content_transport("nu sunt json"))
    with pytest.raises(CopywriterError):
        client.generate(_spec())


def test_incomplete_response_raises_clear_copywriter_error() -> None:
    """Ollama poate raspunde 200 cu 'done': False si continut gol (model corupt /
    incarcare esuata) - vazut real in timpul testarii live pe masina utilizatorului."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "model": "",
            "created_at": "",
            "message": {"role": "", "content": ""},
            "done": False,
        }
        return httpx.Response(200, json=body)

    client = LiveLLMClient(model="llama3", transport=httpx.MockTransport(handler))
    with pytest.raises(CopywriterError, match="intrerupt generarea"):
        client.generate(_spec())


def test_missing_fields_raises_copywriter_error() -> None:
    client = LiveLLMClient(
        model="llama3", transport=_raw_content_transport(json.dumps({"headline_1": "doar asta"}))
    )
    with pytest.raises(CopywriterError):
        client.generate(_spec())


def test_num_gpu_is_included_in_request_options_when_set() -> None:
    captured: list[httpx.Request] = []
    client = LiveLLMClient(
        model="llama3", num_gpu=0, transport=_capturing_transport(_VALID_AD, captured)
    )
    client.generate(_spec())
    body = json.loads(captured[0].content)
    assert body["options"]["num_gpu"] == 0


def test_num_gpu_is_omitted_when_not_set() -> None:
    captured: list[httpx.Request] = []
    client = LiveLLMClient(model="llama3", transport=_capturing_transport(_VALID_AD, captured))
    client.generate(_spec())
    body = json.loads(captured[0].content)
    assert "num_gpu" not in body["options"]


def test_creative_factory_wires_model_and_endpoint_from_settings() -> None:
    cfg = AppConfig(
        settings=Settings(
            _env_file=None,
            provider_mode=ProviderMode.LIVE,
            llm_model="ollama/llama3",
            llm_endpoint="",
        )
    )
    client = CreativeFactory(cfg).llm()
    assert isinstance(client, LiveLLMClient)
    assert client.model == "llama3"
    assert client.endpoint == "http://localhost:11434"


def test_creative_factory_respects_custom_endpoint() -> None:
    cfg = AppConfig(
        settings=Settings(
            _env_file=None,
            provider_mode=ProviderMode.LIVE,
            llm_model="qwen2.5",
            llm_endpoint="http://192.168.1.50:11434",
        )
    )
    client = CreativeFactory(cfg).llm()
    assert isinstance(client, LiveLLMClient)
    assert client.model == "qwen2.5"
    assert client.endpoint == "http://192.168.1.50:11434"


def test_creative_factory_parses_num_gpu_zero_from_settings() -> None:
    cfg = AppConfig(
        settings=Settings(
            _env_file=None,
            provider_mode=ProviderMode.LIVE,
            llm_model="llama3",
            llm_num_gpu="0",
        )
    )
    client = CreativeFactory(cfg).llm()
    assert isinstance(client, LiveLLMClient)
    assert client.num_gpu == 0


def test_creative_factory_leaves_num_gpu_unset_by_default() -> None:
    cfg = AppConfig(
        settings=Settings(_env_file=None, provider_mode=ProviderMode.LIVE, llm_model="llama3")
    )
    client = CreativeFactory(cfg).llm()
    assert isinstance(client, LiveLLMClient)
    assert client.num_gpu is None


def test_ad_copy_generator_end_to_end_with_live_client() -> None:
    """Integrare: AdCopyGenerator (RAG + retry) peste un LiveLLMClient simulat."""
    client = LiveLLMClient(model="llama3", transport=_ok_transport(_VALID_AD))
    generator = AdCopyGenerator(client)
    result = generator.generate_emotional_copy(_USP, "program facturare", "fomo")
    assert set(result) == {"headline_1", "headline_2", "description"}
    assert char_count(result["headline_1"]) <= HEADLINE_LIMIT
    assert char_count(result["description"]) <= DESCRIPTION_LIMIT
