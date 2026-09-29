"""Jev si Ollama simulati: raspunsuri instant, fara retea, peste ``httpx.MockTransport``.

Clientii din teste sunt cei REALI (``JevClient``, ``OllamaChatClient``); doar
serverul e fals. Fiecare fals verifica cererea pe forma documentata a API-ului
(docs.typesafe.ai/api, ``/api/chat`` din Ollama) si raspunde ca serverul real: o
cerere gresita primeste 422 (Jev) / 400 (Ollama) si ajunge in ``problems`` - iar
fixture-urile din ``conftest.py`` pica testul daca ``problems`` nu e gol.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from ppc_agent_server.services.llm_client import (
    JEV_URL,
    MAX_CHOICE_OPTIONS,
    MAX_SCORE_LEVELS,
    MIN_SCORE_LEVELS,
    JevClient,
    LLMRouter,
    OllamaChatClient,
)

JEV_TEST_KEY = "jev_test_key"
OLLAMA_TEST_HOST = "http://localhost:11434"
OLLAMA_TEST_MODEL = "llama3"

#: ``state``-ul si id-ul intrebarii -> raspunsul.
NoulRule = Callable[[Any, str], float]
ScoreRule = Callable[[Any, str], tuple[float, float]]


def _jev_problem(body: Any) -> str | None:
    """Ce e gresit in cererea catre Jev, dupa referinta API-ului; ``None`` = e valida."""
    if not isinstance(body, dict) or set(body) != {"state", "model", "questions"}:
        return "corpul are exact «state», «model» și «questions»"
    if not isinstance(body["model"], str) or not body["model"]:
        return "«model» e un text nevid"
    if not isinstance(body["state"], str | dict | list) or not body["state"]:
        return "«state» e text, obiect sau listă, nevid"
    questions = body["questions"]
    if not isinstance(questions, dict) or not questions:
        return "«questions» e un obiect nevid"
    allowed = {"type", "instructions", "criteria"}
    for qid, question in questions.items():
        if not isinstance(question, dict) or not set(question) <= allowed:
            return f"«{qid}»: doar type, instructions, criteria"
        instructions = question.get("instructions")
        if not isinstance(instructions, str | dict | list) or not instructions:
            return f"«{qid}»: «instructions» lipsește"
        kind = question.get("type")
        criteria = question.get("criteria")
        if kind == "noul":
            if criteria is not None and (
                not isinstance(criteria, dict)
                or not criteria
                or not set(criteria) <= {"true", "false"}
            ):
                return f"«{qid}»: criteriile unui noul sunt doar «true»/«false»"
        elif kind == "choice":
            if not isinstance(criteria, dict) or not 1 <= len(criteria) <= MAX_CHOICE_OPTIONS:
                return f"«{qid}»: un choice are între 1 și {MAX_CHOICE_OPTIONS} opțiuni"
        elif kind == "score":
            if (
                not isinstance(criteria, list)
                or not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS
            ):
                return f"«{qid}»: un score are între 2 și {MAX_SCORE_LEVELS} niveluri"
        else:
            return f"«{qid}»: tip necunoscut {kind!r}"
    return None


class FakeJev:
    """Jev (TypeSafe) simulat.

    Implicit: fiecare ``noul`` e "da" (0,9), fiecare ``score`` alege nivelul 1 cu
    ``confidence`` 0,9, fiecare ``choice`` prima optiune. ``noul_rule`` /
    ``score_rule`` raspund dupa ``state`` si id-ul intrebarii; ``status`` != 200
    simuleaza o eroare (cu ``retry-after: 0`` la 429/529).
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.problems: list[str] = []
        self.noul_rule: NoulRule = lambda state, qid: 0.9
        self.score_rule: ScoreRule = lambda state, qid: (1.0, 0.9)
        self.status = 200
        self.statuses: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) != JEV_URL or request.method != "POST":
            self.problems.append(f"cerere pe {request.method} {request.url}")
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.headers.get("authorization") != f"Bearer {JEV_TEST_KEY}":
            self.problems.append("antetul Authorization lipsește")
            return httpx.Response(401, json={"detail": "Missing or invalid API key"})
        body = json.loads(request.content)
        problem = _jev_problem(body)
        if problem is not None:
            self.problems.append(problem)
            return httpx.Response(422, json={"detail": problem})
        self.requests.append(body)
        status = self.statuses.pop(0) if self.statuses else self.status
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "0"}, json={"detail": "busy"})
        answers = {
            qid: self._answer(body["state"], qid, question)
            for qid, question in body["questions"].items()
        }
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": answers,
                "usage": {"input_tokens": 300, "output_tokens": 20},
            },
        )

    def _answer(self, state: Any, qid: str, question: dict[str, Any]) -> dict[str, Any]:
        kind = question["type"]
        if kind == "noul":
            return {"type": "noul", "noul": self.noul_rule(state, qid)}
        if kind == "choice":
            options = list(question["criteria"])
            probabilities = {option: 0.0 for option in options}
            probabilities[options[0]] = 1.0
            return {
                "type": "choice",
                "choice": options[0],
                "probabilities": probabilities,
                "confidence": 0.9,
            }
        levels = question["criteria"]
        score, confidence = self.score_rule(state, qid)
        chosen = min(max(round(score), 0), len(levels) - 1)
        return {
            "type": "score",
            "score": score,
            "legend": {str(index): level for index, level in enumerate(levels)},
            "probabilities": {
                str(index): (1.0 if index == chosen else 0.0) for index in range(len(levels))
            },
            "confidence": confidence,
        }

    def client(self) -> JevClient:
        return JevClient(
            api_key=JEV_TEST_KEY, transport=httpx.MockTransport(self), sleep=lambda seconds: None
        )

    def router(self) -> LLMRouter:
        return LLMRouter(jev=self.client())


def ndjson_chunks(text: str, *, model: str = OLLAMA_TEST_MODEL) -> list[bytes]:
    """Raspunsul ``/api/chat`` in flux, ca serverul real: cate un rand JSON per fragment.

    Fragmentele sunt cuvintele (cu spatiul lor), iar ultimul rand are ``done: true``
    si mesajul gol - exact forma documentata a fluxului Ollama.
    """
    words = [word + " " for word in text.split(" ")]
    words[-1] = words[-1][:-1]
    lines = [
        {"model": model, "message": {"role": "assistant", "content": word}, "done": False}
        for word in words
        if word
    ]
    lines.append(
        {
            "model": model,
            "created_at": "2026-09-27T10:00:00Z",
            "message": {"role": "assistant", "content": ""},
            "done_reason": "stop",
            "done": True,
        }
    )
    return [json.dumps(line, ensure_ascii=False).encode() + b"\n" for line in lines]


class FakeOllama:
    """Ollama local simulat (``POST /api/chat``, in flux - NDJSON, ca serverul real).

    ``replies``: raspunsul dupa promptul de sistem; ``reply``: pentru restul.
    ``down=True``: serverul nu e pornit (``ConnectError``); ``status`` != 200: eroare.
    ``silent=True``: accepta conexiunea, dar nu trimite niciun token (termenul primului
    token expira). ``stall_after=n``: trimite ``n`` fragmente, apoi tace.
    """

    def __init__(self, reply: str = "Mesajul modelului local.") -> None:
        self.reply = reply
        self.replies: dict[str, str] = {}
        self.requests: list[dict[str, Any]] = []
        self.problems: list[str] = []
        self.down = False
        self.silent = False
        self.stall_after: int | None = None
        self.status = 200
        self.connections = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.connections += 1
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if str(request.url) != f"{OLLAMA_TEST_HOST}/api/chat" or request.method != "POST":
            self.problems.append(f"cerere pe {request.method} {request.url}")
            return httpx.Response(404, text="404 page not found")
        body = json.loads(request.content)
        problem = self._problem(body)
        if problem is not None:
            self.problems.append(problem)
            return httpx.Response(400, json={"error": problem})
        self.requests.append(body)
        if self.silent:
            raise httpx.ReadTimeout("niciun token", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "llama runner has terminated"})
        system = body["messages"][0]["content"]
        chunks = ndjson_chunks(self.replies.get(system, self.reply), model=body["model"])
        stall_after = self.stall_after

        def stream() -> Iterator[bytes]:
            for index, chunk in enumerate(chunks):
                if stall_after is not None and index >= stall_after:
                    raise httpx.ReadTimeout("generarea s-a blocat", request=request)
                yield chunk

        return httpx.Response(
            200, headers={"content-type": "application/x-ndjson"}, content=stream()
        )

    @staticmethod
    def _problem(body: Any) -> str | None:
        if not isinstance(body, dict) or body.get("model") != OLLAMA_TEST_MODEL:
            return "«model» lipsește sau nu e cel configurat"
        if body.get("stream") is not True:
            return "«stream» trebuie să fie true (răspunsul vine în flux)"
        messages = body.get("messages")
        roles = [m.get("role") for m in messages] if isinstance(messages, list) else None
        if roles != ["system", "user"]:
            return "«messages» = sistem, apoi utilizator"
        if not all(isinstance(m.get("content"), str) and m["content"] for m in messages):
            return "fiecare mesaj are «content» nevid"
        options = body.get("options")
        if not isinstance(options, dict) or not set(options) <= {"temperature", "num_predict"}:
            return "«options» are doar temperature și num_predict"
        keep_alive = body.get("keep_alive", "5m")
        if not isinstance(keep_alive, str) or not keep_alive:
            return "«keep_alive» e o durată, ca «30m»"
        if not set(body) <= {"model", "messages", "stream", "options", "keep_alive"}:
            return "chei necunoscute în cerere"
        return None

    def user_prompts(self) -> list[str]:
        return [body["messages"][1]["content"] for body in self.requests]

    def client(self) -> OllamaChatClient:
        return OllamaChatClient(
            host=OLLAMA_TEST_HOST, model=OLLAMA_TEST_MODEL, transport=httpx.MockTransport(self)
        )

    def router(self) -> LLMRouter:
        return LLMRouter(ollama=self.client())
