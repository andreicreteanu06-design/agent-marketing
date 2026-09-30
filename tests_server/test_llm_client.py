"""Ruterul hibrid: Jev (Sistemul 1) si Ollama (Sistemul 2) - forma cererilor, erorile, rutarea.

Fara retea: serverele sunt ``httpx.MockTransport`` (``tests_server/llm_fakes.py``
sau un handler local), clientii sunt cei reali.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from ppc_agent_server.services.llm_client import (
    DEFAULT_JEV_MODEL,
    DEFAULT_OLLAMA_MODEL,
    JEV_URL,
    OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS,
    ROUTES,
    Choice,
    ChoiceAnswer,
    JevClient,
    JevError,
    LLMRouter,
    LLMUnavailableError,
    Noul,
    NoulAnswer,
    OllamaChatClient,
    OllamaError,
    Score,
    ScoreAnswer,
    _ThinkingFilter,
    llm_router_from_settings,
)
from ppc_agent_server.settings import DEFAULT_OLLAMA_HOST, ServerSettings, normalize_ollama_host
from tests_server.llm_fakes import JEV_TEST_KEY, OLLAMA_TEST_HOST, FakeJev, FakeOllama

URGENT = Noul("Does this convey urgency?", true="Explicitly time-sensitive", false="No urgency")
DEPARTMENT = Choice(
    "Which team should handle this?",
    {"billing": "Payments, invoicing, refunds", "technical": "Bugs, outages", "sales": None},
)
FRUSTRATION = Score("How frustrated is the customer?", ("Calm", "Frustrated", "Very angry"))
TICKET = "Help! My payouts have been failing for 3 days."


def _jev(handler: Any, **kwargs: Any) -> JevClient:
    return JevClient(
        api_key=JEV_TEST_KEY, transport=httpx.MockTransport(handler), sleep=lambda s: None, **kwargs
    )


def _jev_ok(answers: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200, json={"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 3}}
    )


DOCUMENTED_ANSWERS = {
    "is_urgent": {"type": "noul", "noul": 0.95},
    "department": {
        "type": "choice",
        "choice": "billing",
        "probabilities": {"billing": 0.88, "technical": 0.12, "sales": 0.0},
        "confidence": 0.81,
    },
    "frustration": {
        "type": "score",
        "score": 1.05,
        "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
        "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
        "confidence": 0.92,
    },
}
QUESTIONS = {"is_urgent": URGENT, "department": DEPARTMENT, "frustration": FRUSTRATION}


# --- Jev: cererea ---------------------------------------------------------------------


def test_jev_request_has_the_documented_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _jev_ok(DOCUMENTED_ANSWERS)

    _jev(handler).system_one(TICKET, QUESTIONS)

    [request] = seen
    assert (request.method, str(request.url)) == ("POST", JEV_URL)
    assert request.url.host == "api.typesafe.ai" and request.url.path == "/v1/systemone"
    assert request.headers["Authorization"] == f"Bearer {JEV_TEST_KEY}"
    assert json.loads(request.content) == {
        "state": TICKET,
        "model": DEFAULT_JEV_MODEL,
        "questions": {
            "is_urgent": {
                "type": "noul",
                "instructions": "Does this convey urgency?",
                "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency"},
            },
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "Payments, invoicing, refunds",
                    "technical": "Bugs, outages",
                    "sales": None,
                },
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated is the customer?",
                "criteria": ["Calm", "Frustrated", "Very angry"],
            },
        },
    }


def test_a_noul_without_criteria_sends_none(fake_jev: FakeJev) -> None:
    fake_jev.client().system_one({"ticket": TICKET}, {"urgent": Noul("Is it urgent?")})

    [body] = fake_jev.requests
    assert body["questions"]["urgent"] == {"type": "noul", "instructions": "Is it urgent?"}
    assert body["state"] == {"ticket": TICKET}


@pytest.mark.parametrize(
    "question",
    [
        Choice("Pick one", {"only": None}),
        Choice("Pick one", {f"option_{i}": None for i in range(256)}),
        Score("Rate it", ("single",)),
        Score("Rate it", tuple(f"level {i}" for i in range(11))),
        Noul("   "),
    ],
    ids=["choice-1", "choice-256", "score-1", "score-11", "fara-instructiuni"],
)
def test_questions_outside_the_api_limits_are_refused_before_sending(question: Any) -> None:
    sent: list[httpx.Request] = []
    client = _jev(lambda request: sent.append(request) or _jev_ok({}))
    with pytest.raises(ValueError):
        client.system_one(TICKET, {"q": question})
    with pytest.raises(ValueError, match="cel puțin o întrebare"):
        client.system_one(TICKET, {})
    assert sent == []


# --- Jev: raspunsul -----------------------------------------------------------------


def test_jev_answers_come_back_typed() -> None:
    answers = _jev(lambda request: _jev_ok(DOCUMENTED_ANSWERS)).system_one(TICKET, QUESTIONS)

    assert answers["is_urgent"] == NoulAnswer(0.95)
    assert answers["is_urgent"].yes()
    assert answers["department"] == ChoiceAnswer(
        "billing", {"billing": 0.88, "technical": 0.12, "sales": 0.0}, 0.81
    )
    frustration = answers["frustration"]
    assert isinstance(frustration, ScoreAnswer)
    assert (frustration.score, frustration.level, frustration.confidence) == (1.05, 1, 0.92)


@pytest.mark.parametrize(
    ("score", "level"), [(0.0, 0), (0.49, 0), (0.5, 1), (1.5, 2), (2.4, 2), (7.0, 2), (-1.0, 0)]
)
def test_the_score_level_is_the_threshold_it_passed_on_the_scale(score: float, level: int) -> None:
    legend = {"0": "Calm", "1": "Frustrated", "2": "Very angry"}
    assert ScoreAnswer(score, legend, {"0": 1.0}, 0.9).level == level


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, json={"detail": "Missing or invalid API key"}), "401: Missing"),
        (httpx.Response(422, json={"detail": "questions.x.type"}), "422: questions.x.type"),
        (httpx.Response(500, text="boom"), "500: boom"),
        (httpx.Response(200, text="nu e json"), "nu e JSON"),
        (httpx.Response(200, json={"model": "jev"}), "fără «answers»"),
        (_jev_ok({**DOCUMENTED_ANSWERS, "is_urgent": {"type": "noul", "noul": 1.7}}), "is_urgent"),
        (_jev_ok({**DOCUMENTED_ANSWERS, "is_urgent": {"type": "score"}}), "is_urgent"),
        (
            _jev_ok({**DOCUMENTED_ANSWERS, "department": {**DOCUMENTED_ANSWERS["department"],
                                                          "choice": "legal"}}),
            "department",
        ),
        (
            _jev_ok({**DOCUMENTED_ANSWERS, "frustration": {**DOCUMENTED_ANSWERS["frustration"],
                                                           "legend": {"0": "Calm"}}}),
            "frustration",
        ),
        (_jev_ok({"is_urgent": DOCUMENTED_ANSWERS["is_urgent"]}), "department"),
    ],
)
def test_unusable_jev_answers_raise_without_leaking_the_key(
    response: httpx.Response, expected: str
) -> None:
    with pytest.raises(JevError, match=expected) as excinfo:
        _jev(lambda request: response).system_one(TICKET, QUESTIONS)
    assert JEV_TEST_KEY not in str(excinfo.value)


@pytest.mark.parametrize("status", [429, 529])
def test_a_rate_limit_or_overload_is_retried_once(fake_jev: FakeJev, status: int) -> None:
    waits: list[float] = []
    client = JevClient(
        api_key=JEV_TEST_KEY, transport=httpx.MockTransport(fake_jev), sleep=waits.append
    )
    fake_jev.statuses = [status]

    answers = client.system_one(TICKET, {"is_urgent": URGENT})

    assert answers["is_urgent"] == NoulAnswer(0.9)
    assert len(fake_jev.requests) == 2
    assert waits == [0.0]  # retry-after: 0

    fake_jev.statuses = [status, status]
    with pytest.raises(JevError, match=str(status)):
        client.system_one(TICKET, {"is_urgent": URGENT})


def test_network_errors_become_jev_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fara retea", request=request)

    with pytest.raises(JevError, match="ConnectError"):
        _jev(handler).system_one(TICKET, {"is_urgent": URGENT})


# --- Ollama -----------------------------------------------------------------------------


def test_ollama_chat_request_and_answer(fake_ollama: FakeOllama) -> None:
    fake_ollama.reply = "  Textul Reginei.  "

    text = fake_ollama.client().complete(system="rol", user="fapte")

    assert text == "Textul Reginei."
    [body] = fake_ollama.requests
    assert body == {
        "model": "llama3",
        "messages": [{"role": "system", "content": "rol"}, {"role": "user", "content": "fapte"}],
        "stream": True,
        "options": {"temperature": 0.3, "num_predict": 450},
        "keep_alive": "30m",
    }


def test_the_answer_arrives_token_by_token(fake_ollama: FakeOllama) -> None:
    fake_ollama.reply = "Contul e rentabil, deci creștem treptat."

    chunks = list(fake_ollama.client().stream(system="s", user="u"))

    assert chunks == ["Contul ", "e ", "rentabil, ", "deci ", "creștem ", "treptat."]
    assert "".join(chunks) == fake_ollama.reply


def test_nothing_is_sent_before_the_first_read(fake_ollama: FakeOllama) -> None:
    stream = fake_ollama.client().stream(system="s", user="u")

    assert fake_ollama.connections == 0
    assert next(stream) == "Mesajul "
    assert fake_ollama.connections == 1


def test_the_server_default_keep_alive_can_be_kept(fake_ollama: FakeOllama) -> None:
    client = OllamaChatClient(
        host=OLLAMA_TEST_HOST, keep_alive=None, transport=httpx.MockTransport(fake_ollama)
    )

    client.complete(system="s", user="u")

    assert "keep_alive" not in fake_ollama.requests[0]


def test_the_reasoning_of_thinking_models_never_reaches_the_client(
    fake_ollama: FakeOllama,
) -> None:
    fake_ollama.reply = "<think>\nClientul vrea bani...\n</think>\n\nRăspunsul final."

    assert fake_ollama.client().complete(system="s", user="u") == "Răspunsul final."
    streamed = list(fake_ollama.client().stream(system="s", user="u"))
    assert "".join(streamed) == "Răspunsul final."
    assert not any("think" in chunk or "Clientul" in chunk for chunk in streamed)


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["<th", "ink>plan</th", "ink>", "\n\nGata."], "Gata."),
        (["  <think>", "doar gânduri"], ""),
        (["<th", "is is not a tag"], "<this is not a tag"),
        (["Direct", " răspunsul."], "Direct răspunsul."),
    ],
)
def test_the_thinking_filter_works_across_chunk_boundaries(
    chunks: list[str], expected: str
) -> None:
    thinking = _ThinkingFilter()

    text = "".join(thinking.feed(chunk) for chunk in chunks) + thinking.flush()

    assert text == expected


def _ollama(response: httpx.Response) -> OllamaChatClient:
    return OllamaChatClient(
        host=OLLAMA_TEST_HOST, transport=httpx.MockTransport(lambda request: response)
    )


def _ndjson(*lines: dict[str, Any]) -> httpx.Response:
    body = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    return httpx.Response(200, content=body)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(404, json={"error": "model 'llama3' not found"}),
            "not found - dacă lipsește modelul: ollama pull llama3",
        ),
        (httpx.Response(500, json={"error": "llama runner process has terminated"}), "500"),
        (httpx.Response(200, text="nu e json"), "nu e JSON"),
        (_ndjson({"done": True}), "gol"),
        (_ndjson({"message": {"content": "   "}, "done": True}), "gol"),
        (_ndjson({"message": {"content": None}, "done": False}), "neașteptat"),
        (_ndjson({"message": {"content": "Jum"}, "done": False}), "întrerupt"),
        (_ndjson({"message": {"content": "Jum"}, "done": False}, {"error": "out of memory"}),
         "întrerupt generarea: out of memory"),
    ],
)
def test_unusable_ollama_answers_raise(response: httpx.Response, expected: str) -> None:
    with pytest.raises(OllamaError, match=expected):
        _ollama(response).complete(system="s", user="u")


def test_ollama_down_fails_fast_until_the_cooldown_passes(fake_ollama: FakeOllama) -> None:
    now = [100.0]
    client = OllamaChatClient(
        host=OLLAMA_TEST_HOST,
        transport=httpx.MockTransport(fake_ollama),
        cooldown=30.0,
        clock=lambda: now[0],
    )
    fake_ollama.down = True

    with pytest.raises(LLMUnavailableError, match="ollama serve"):
        client.complete(system="s", user="u")
    now[0] += 29.0
    with pytest.raises(LLMUnavailableError, match="de curând"):
        client.complete(system="s", user="u")
    assert fake_ollama.connections == 1  # in pauza, nu se mai asteapta niciun timeout

    fake_ollama.down = False
    now[0] += 2.0
    assert client.complete(system="s", user="u") == fake_ollama.reply
    assert fake_ollama.connections == 2


def test_no_first_token_in_time_trips_the_circuit_breaker(fake_ollama: FakeOllama) -> None:
    fake_ollama.silent = True
    client = fake_ollama.client()

    with pytest.raises(OllamaError, match="n-a trimis niciun token în 180 s"):
        client.complete(system="s", user="u")
    # Urmatoarea conversatie, in pauza serverului: direct pe template.
    with pytest.raises(LLMUnavailableError, match="de curând"):
        client.complete(system="s", user="u")
    assert fake_ollama.connections == 1


def test_bytes_without_a_single_token_still_count_as_no_first_token() -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 4.0  # fiecare rand gol din flux "dureaza" 4 s
        return now[0]

    empty = {"message": {"role": "assistant", "content": ""}, "done": False}
    client = OllamaChatClient(
        host=OLLAMA_TEST_HOST,
        transport=httpx.MockTransport(lambda request: _ndjson(*[empty] * 5)),
        clock=clock,
        first_token_timeout=10.0,
    )

    with pytest.raises(OllamaError, match="niciun token în 10 s"):
        client.complete(system="s", user="u")
    with pytest.raises(LLMUnavailableError, match="de curând"):
        client.complete(system="s", user="u")


def test_a_slow_model_that_keeps_writing_is_never_cut(fake_ollama: FakeOllama) -> None:
    """Cat timp curg tokeni, generarea nu are termen de raspuns (doar plasa de 300 s)."""
    now = [0.0]

    def clock() -> float:
        now[0] += 9.0  # 9 s intre tokeni: peste cele 60 s de odinioara, la final
        return now[0]

    fake_ollama.reply = " ".join(["cuvânt"] * 12)
    client = OllamaChatClient(
        host=OLLAMA_TEST_HOST, transport=httpx.MockTransport(fake_ollama), clock=clock
    )

    assert client.complete(system="s", user="u") == fake_ollama.reply


def test_a_generation_stuck_midway_fails_without_resting_the_server(
    fake_ollama: FakeOllama,
) -> None:
    fake_ollama.reply = "Unu doi trei patru."
    fake_ollama.stall_after = 2
    client = fake_ollama.client()
    received: list[str] = []

    with pytest.raises(OllamaError, match="s-a oprit în mijlocul răspunsului"):
        for chunk in client.stream(system="s", user="u"):
            received.append(chunk)

    assert received == ["Unu ", "doi "]
    fake_ollama.stall_after = None
    assert client.complete(system="s", user="u") == "Unu doi trei patru."


def test_generations_on_one_server_wait_their_turn(fake_ollama: FakeOllama) -> None:
    client = OllamaChatClient(
        host=OLLAMA_TEST_HOST,
        transport=httpx.MockTransport(fake_ollama),
        max_parallel=1,
        queue_timeout=0.05,
    )
    first = client.stream(system="s", user="u")
    assert next(first) == "Mesajul "  # prima generare tine locul

    with pytest.raises(OllamaError, match="ocupat"):
        client.complete(system="s", user="u")
    assert fake_ollama.connections == 1  # a doua n-a plecat spre server

    first.close()  # consumatorul renunta: locul se elibereaza
    assert client.complete(system="s", user="u") == fake_ollama.reply


# --- ruterul ----------------------------------------------------------------------------


def test_each_task_goes_to_its_system() -> None:
    assert ROUTES == {
        "classify": "jev",
        "score": "jev",
        "verify": "jev",
        "generate": "ollama",
    }
    assert [LLMRouter.backend(task) for task in ("classify", "generate")] == ["jev", "ollama"]


def test_a_missing_system_is_unavailable_not_silently_replaced(
    fake_jev: FakeJev, fake_ollama: FakeOllama
) -> None:
    nothing = LLMRouter()
    assert not any(nothing.ready(task) for task in ROUTES)
    assert nothing.voice is None
    with pytest.raises(LLMUnavailableError, match="JEV_API_KEY"):
        nothing.jev_verify(TICKET, URGENT)
    with pytest.raises(LLMUnavailableError, match="OLLAMA_HOST"):
        nothing.generate_text_local(system="s", user="u")

    only_jev = fake_jev.router()
    assert only_jev.ready("score") and not only_jev.ready("generate")
    assert only_jev.voice is None
    only_ollama = fake_ollama.router()
    assert only_ollama.voice is only_ollama and not only_ollama.ready("verify")
    assert fake_jev.requests == [] and fake_ollama.requests == []


def test_system_one_helpers(fake_jev: FakeJev) -> None:
    router = fake_jev.router()
    fake_jev.noul_rule = lambda state, qid: 0.3

    assert router.jev_verify(TICKET, URGENT) is False
    assert router.jev_verify(TICKET, URGENT, threshold=0.25) is True
    assert router.jev_classify(TICKET, DEPARTMENT).choice == "billing"
    scores = router.jev_score(TICKET, {"frustration": FRUSTRATION, "again": FRUSTRATION})
    assert {qid: answer.level for qid, answer in scores.items()} == {"frustration": 1, "again": 1}
    # Toate scarile pe acelasi state: o singura cerere.
    assert [sorted(body["questions"]) for body in fake_jev.requests[-1:]] == [
        ["again", "frustration"]
    ]
    assert len(fake_jev.requests) == 4


def test_the_router_is_the_voice_and_writes_only_through_ollama(
    fake_jev: FakeJev, fake_ollama: FakeOllama
) -> None:
    router = LLMRouter(jev=fake_jev.client(), ollama=fake_ollama.client())

    assert router.voice is router
    assert router.model == "llama3"
    assert router.complete(system="s", user="u") == fake_ollama.reply
    assert "".join(router.stream(system="s", user="u")) == fake_ollama.reply
    assert len(fake_ollama.requests) == 2 and fake_jev.requests == []
    with pytest.raises(LLMUnavailableError, match="OLLAMA_HOST"):
        next(LLMRouter().stream_text_local(system="s", user="u"))


# --- setarile -----------------------------------------------------------------------------


def test_router_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    nothing = llm_router_from_settings(ServerSettings(jev_api_key="", ollama_host=""))
    assert not any(nothing.ready(task) for task in ROUTES)

    both = llm_router_from_settings(ServerSettings(jev_api_key="jev_x", ollama_host="localhost"))
    assert both.ready("score") and both.ready("generate")
    assert both.model == DEFAULT_OLLAMA_MODEL

    custom = llm_router_from_settings(
        ServerSettings(ollama_host="localhost", ollama_model="ollama/qwen2.5:7b")
    )
    assert custom.model == "qwen2.5:7b"


def test_the_streaming_limits_come_from_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_FIRST_TOKEN_TIMEOUT", "15")
    monkeypatch.setenv("OLLAMA_MAX_PARALLEL", "4")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "2h")

    settings = ServerSettings(_env_file=None, ollama_host="localhost")
    client = llm_router_from_settings(settings)._local()

    assert (client.first_token_timeout, client.max_parallel, client.keep_alive) == (
        15.0,
        4,
        "2h",
    )
    defaults = ServerSettings(_env_file=None, ollama_host="localhost", ollama_keep_alive="")
    assert llm_router_from_settings(defaults)._local().keep_alive is None
    with pytest.raises(ValidationError):
        ServerSettings(_env_file=None, ollama_first_token_timeout=0)


def test_settings_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JEV_API_KEY")
    monkeypatch.delenv("OLLAMA_HOST")

    settings = ServerSettings(_env_file=None)

    assert (settings.jev_api_key, settings.ollama_host) == ("", DEFAULT_OLLAMA_HOST)
    # Sinteza consiliului porneste pe CPU in ~45 s: termenul ii lasa loc larg.
    assert settings.ollama_first_token_timeout == OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS == 180.0
    assert DEFAULT_OLLAMA_HOST == "http://localhost:11434"


def test_settings_read_and_clean_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "  jev_live_123  ")
    monkeypatch.setenv("OLLAMA_HOST", "host.docker.internal")

    settings = ServerSettings(_env_file=None)

    assert settings.jev_api_key == "jev_live_123"
    assert settings.ollama_host == "http://host.docker.internal:11434"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("localhost", "http://localhost:11434"),
        ("127.0.0.1:12345", "http://127.0.0.1:12345"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("http://host.docker.internal:11434/", "http://host.docker.internal:11434"),
        ("http://gpu-box", "http://gpu-box:80"),
        ("https://llm.example.com/ollama/", "https://llm.example.com:443/ollama"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_ollama_host_is_read_like_the_official_client(raw: str, expected: str) -> None:
    assert normalize_ollama_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["ftp://localhost", "http://user:parola@localhost", "localhost:99999", "http://gpu?x=1", "http://"],
)
def test_invalid_ollama_hosts_stop_the_startup(raw: str) -> None:
    with pytest.raises(ValidationError, match="OLLAMA_HOST"):
        ServerSettings(ollama_host=raw)


def test_a_jev_key_with_spaces_is_refused() -> None:
    with pytest.raises(ValidationError, match="spații"):
        ServerSettings(jev_api_key="jev abc")
