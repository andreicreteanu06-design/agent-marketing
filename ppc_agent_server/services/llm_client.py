"""Ruterul LLM hibrid: Sistemul 1 (Jev) decide, Sistemul 2 (Ollama, local) scrie.

Doua feluri de munca, doua modele:

- **Sistemul 1 - Jev** (TypeSafe AI, ``POST https://api.typesafe.ai/v1/systemone``):
  decizii structurate si rapide - alege o optiune (``choice``), noteaza pe o scara
  ordonata (``score``), raspunde da/nu (``noul``). Nu scrie text: intoarce raspunsuri
  tipizate, cu probabilitati si ``confidence``, si se plateste doar pe tokenii de
  intrare. Aici: :meth:`LLMRouter.jev_classify`, :meth:`~LLMRouter.jev_score`,
  :meth:`~LLMRouter.jev_verify`.
- **Sistemul 2 - Ollama** (``POST {OLLAMA_HOST}/api/chat``, pe masina noastra): tot
  textul scris pentru client - mesajul CMO al Reginei si sinteza consiliului (membrii
  consiliului vorbesc din date, fara model). Aici:
  :meth:`LLMRouter.generate_text_local` (textul intreg) si
  :meth:`LLMRouter.stream_text_local` (token cu token, pentru chatul in timp real);
  ruterul e si ``TextGenerator``-ul pe care il primesc Regina si consiliul, deci orice
  generare trece pe acolo.

:class:`LLMRouter` trimite fiecare sarcina (``task_type``, vezi :data:`ROUTES`) la
sistemul ei. Ce nu e configurat, sau nu raspunde, ridica :class:`LLMError`, iar
apelantii cad pe varianta determinista: template-urile consiliului, estimarile RICE
din tabel, toate fragmentele web. Modulul nu decide nimic despre client: stie doar
sa intrebe si sa verifice forma raspunsului.

Jev, dupa documentatia lui (docs.typesafe.ai, ``jev-1.13``):

- intrebarile si criteriile se scriu in engleza, unde modelul e cel mai precis;
  continutul clientului sta in ``state``, in romana;
- aritmetica ramane in cod: un ``score`` alege un NIVEL, valoarea lui o da codul;
- sub :data:`MIN_CONFIDENCE` (0,5 - pragul "nu ghici" din documentatie) raspunsul
  nu se foloseste;
- 429/529 (limita, suprasarcina) -> o singura reincercare, dupa ``retry-after``.

Ollama raspunde mereu in flux (``"stream": true``), ca pe CPU un raspuns lung sa nu
mai loveasca un timeout total: cat timp vin tokeni, generarea continua. Circuit-breaker-ul
sare doar cand Ollama nu raspunde deloc (conexiune picata) sau nu trimite niciun token
in :data:`OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS` - atunci apelurile cad direct pe template
:data:`OLLAMA_COOLDOWN_SECONDS`, fara sa mai astepte fiecare. Cererile catre acelasi
server trec pe rand (:data:`OLLAMA_MAX_PARALLEL`), ca termenul primului token sa masoare
modelul, nu coada din fata lui.

Fara SDK-uri (``typesafe-sdk``, ``ollama``): doar ``httpx``, deja dependinta.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, TypeAlias, TypeVar

import httpx

from ppc_agent_server.settings import ServerSettings

logger = logging.getLogger("ppc_agent_server.services.llm_client")

#: Orice e JSON: ce poate intra in ``state``-ul unei cereri Jev.
JsonValue: TypeAlias = (
    "str | int | float | bool | Sequence[JsonValue] | Mapping[str, JsonValue] | None"
)

#: Cat din corpul unui raspuns de eroare ajunge in mesaj (si in log-uri).
_ERROR_DETAIL_CHARS = 200


class LLMError(RuntimeError):
    """Un model nu a dat un raspuns utilizabil - apelantul cade pe varianta determinista."""


class LLMUnavailableError(LLMError):
    """Sistemul cerut nu e configurat sau nu raspunde deloc (nepornit, alta adresa)."""


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:_ERROR_DETAIL_CHARS]
    if isinstance(body, dict):
        error = body.get("error") or body.get("detail")
        if isinstance(error, dict):
            error = error.get("message") or error
        if error:
            return str(error)[:_ERROR_DETAIL_CHARS]
    return str(body)[:_ERROR_DETAIL_CHARS]


# --- Sistemul 1: Jev ---------------------------------------------------------------

JEV_URL = "https://api.typesafe.ai/v1/systemone"
#: Ultima versiune stabila (azi ``jev-1.13.0``); raspunsul spune ce versiune a raspuns.
DEFAULT_JEV_MODEL = "jev-latest"
#: Implicitul SDK-ului oficial, pe operatie HTTP.
JEV_TIMEOUT_SECONDS = 10.0
#: Sub atat, un raspuns Choice/Score nu se foloseste (pragul "nu ghici" din documentatie).
MIN_CONFIDENCE = 0.5
#: De la cat un ``noul`` e "da".
YES = 0.5
#: Limitele documentate ale API-ului.
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10
#: 429 = limita depasita, 529 = TypeSafe suprasolicitat: se reincearca o data.
_RETRY_STATUSES = frozenset({429, 529})
_RETRY_WAIT_SECONDS = 0.5
_MAX_RETRY_WAIT_SECONDS = 2.0


class JevError(LLMError):
    """Jev nu a intors un raspuns utilizabil (retea, cheie, limita, forma)."""


def _instructions(text: str) -> str:
    if not text.strip():
        raise ValueError("o întrebare Jev are nevoie de «instructions»")
    return text


@dataclass(frozen=True, slots=True)
class Noul:
    """Intrebare da/nu: Jev intoarce probabilitatea ca raspunsul sa fie "da"."""

    type: ClassVar[str] = "noul"
    instructions: str
    #: Ce inseamna "da", respectiv "nu" - optional, dar scade citirea "literala".
    true: str | None = None
    false: str | None = None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"type": self.type, "instructions": _instructions(self.instructions)}
        criteria = {key: text for key, text in (("true", self.true), ("false", self.false)) if text}
        if criteria:
            body["criteria"] = criteria
        return body


@dataclass(frozen=True, slots=True)
class Choice:
    """Alege una dintre optiuni; Jev intoarce optiunea, probabilitatile si ``confidence``."""

    type: ClassVar[str] = "choice"
    instructions: str
    #: Optiunea -> descrierea ei (``None`` = fara detalii). Intre 2 si 255.
    options: Mapping[str, str | None]

    def payload(self) -> dict[str, Any]:
        if not 2 <= len(self.options) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"un Choice are între 2 și {MAX_CHOICE_OPTIONS} opțiuni")
        return {
            "type": self.type,
            "instructions": _instructions(self.instructions),
            "criteria": dict(self.options),
        }


@dataclass(frozen=True, slots=True)
class Score:
    """Noteaza pe o scara ordonata; Jev intoarce pozitia (poate cadea intre niveluri)."""

    type: ClassVar[str] = "score"
    instructions: str
    #: Nivelurile, de la cel mai mic la cel mai mare. Intre 2 si 10.
    levels: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        if not MIN_SCORE_LEVELS <= len(self.levels) <= MAX_SCORE_LEVELS:
            raise ValueError(
                f"un Score are între {MIN_SCORE_LEVELS} și {MAX_SCORE_LEVELS} niveluri"
            )
        return {
            "type": self.type,
            "instructions": _instructions(self.instructions),
            "criteria": list(self.levels),
        }


Question: TypeAlias = Noul | Choice | Score


@dataclass(frozen=True, slots=True)
class NoulAnswer:
    #: 0 = nu, 1 = da.
    noul: float

    def yes(self, threshold: float = YES) -> bool:
        return self.noul >= threshold


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    #: Pozitia ponderata pe scara (0 = primul nivel); poate cadea intre niveluri.
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float

    @property
    def level(self) -> int:
        """Nivelul ales: pozitia rotunjita (prag la jumatate), in limitele scarii.

        Documentatia: scorul spune doar ce prag a trecut, nu o valoare intre niveluri.
        """
        top = max(len(self.legend) - 1, 0)
        return min(max(math.floor(self.score + 0.5), 0), top)


Answer: TypeAlias = NoulAnswer | ChoiceAnswer | ScoreAnswer
_Typed = TypeVar("_Typed", NoulAnswer, ChoiceAnswer, ScoreAnswer)


def _unexpected(question_id: str) -> JevError:
    return JevError(f"Jev a întors un răspuns neașteptat pentru «{question_id}»")


def _number(value: object, question_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _unexpected(question_id)
    return float(value)


def _unit(value: object, question_id: str) -> float:
    number = _number(value, question_id)
    if not 0.0 <= number <= 1.0:
        raise _unexpected(question_id)
    return number


def _distribution(value: object, question_id: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise _unexpected(question_id)
    return {str(key): _unit(probability, question_id) for key, probability in value.items()}


def _answer(question_id: str, question: Question, raw: object) -> Answer:
    """Raspunsul pentru o intrebare, verificat pe forma documentata a API-ului."""
    if not isinstance(raw, dict) or raw.get("type") != question.type:
        raise _unexpected(question_id)
    if isinstance(question, Noul):
        return NoulAnswer(_unit(raw.get("noul"), question_id))
    confidence = _unit(raw.get("confidence"), question_id)
    probabilities = _distribution(raw.get("probabilities"), question_id)
    if isinstance(question, Choice):
        choice = raw.get("choice")
        if not isinstance(choice, str) or choice not in question.options:
            raise _unexpected(question_id)
        return ChoiceAnswer(choice, probabilities, confidence)
    legend = raw.get("legend")
    if not isinstance(legend, dict) or len(legend) != len(question.levels):
        raise _unexpected(question_id)
    return ScoreAnswer(
        score=_number(raw.get("score"), question_id),
        legend={str(key): str(text) for key, text in legend.items()},
        probabilities=probabilities,
        confidence=confidence,
    )


def _typed(question_id: str, answer: Answer, kind: type[_Typed]) -> _Typed:
    if not isinstance(answer, kind):
        raise _unexpected(question_id)
    return answer


def _retry_wait(response: httpx.Response) -> float:
    try:
        wait = float(response.headers.get("retry-after", _RETRY_WAIT_SECONDS))
    except ValueError:
        wait = _RETRY_WAIT_SECONDS
    return min(max(wait, 0.0), _MAX_RETRY_WAIT_SECONDS)


@dataclass(frozen=True, slots=True)
class JevClient:
    """Clientul HTTP pentru Jev: ``state`` + intrebari tipizate -> raspunsuri tipizate."""

    api_key: str
    model: str = DEFAULT_JEV_MODEL
    timeout: float = JEV_TIMEOUT_SECONDS
    url: str = JEV_URL
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep

    def system_one(
        self, state: JsonValue, questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        """Toate intrebarile, evaluate intr-o singura cerere, pe acelasi ``state``.

        Raises:
            ValueError: nicio intrebare, sau o intrebare in afara limitelor API-ului.
            JevError: retea, cheie, limita sau un raspuns fara forma documentata -
                fara cheia in mesaj.
        """
        if not questions:
            raise ValueError("Jev are nevoie de cel puțin o întrebare")
        payload = {
            "state": state,
            "model": self.model,
            "questions": {qid: question.payload() for qid, question in questions.items()},
        }
        response = self._post(payload)
        if response.status_code in _RETRY_STATUSES:
            self.sleep(_retry_wait(response))
            response = self._post(payload)
        if response.status_code != 200:
            raise JevError(f"Jev a răspuns {response.status_code}: {_error_detail(response)}")
        try:
            body = response.json()
        except ValueError as exc:
            raise JevError("Jev a întors un răspuns neașteptat (nu e JSON)") from exc
        answers = body.get("answers") if isinstance(body, dict) else None
        if not isinstance(answers, dict):
            raise JevError("Jev a întors un răspuns fără «answers»")
        parsed = {qid: _answer(qid, q, answers.get(qid)) for qid, q in questions.items()}
        usage = body.get("usage")
        logger.debug("[Jev] %s: %d răspunsuri, %s", body.get("model"), len(parsed), usage)
        return parsed

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                return client.post(
                    self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload
                )
        except httpx.HTTPError as exc:
            raise JevError(f"Jev nu a răspuns ({type(exc).__name__})") from exc


# --- Sistemul 2: Ollama ------------------------------------------------------------

#: Acelasi model ca la copywriterul din CLI (``PPC_LLM_MODEL``): un singur ``ollama pull``.
DEFAULT_OLLAMA_MODEL = "llama3"
#: Serverul e local: daca nu accepta conexiunea in 2 s, nu e pornit.
OLLAMA_CONNECT_TIMEOUT_SECONDS = 2.0
#: Circuit-breaker-ul: fara niciun token in atat (modelul se incarca, citeste promptul
#: sau e prea mare pentru masina), Ollama intra in pauza si raspunde template-ul. Tot
#: atat poate tacea si in mijlocul raspunsului inainte sa-l socotim blocat. Generos:
#: singurul apel al consiliului e sinteza Reginei, al carei prompt (~2-3k tokeni) un
#: model mic il citeste pe CPU in ~45 s - de patru ori mai putin decat termenul, ca un
#: CPU ocupat sau un cont cu mai multe date sa nu-l depaseasca. Chatul vine in flux
#: (SSE), deci asteptarea se vede, nu arata ca o pagina blocata.
OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS = 180.0
#: Plafonul unei generari intregi, cat timp tokenii curg: pe CPU, 450 de tokeni pot
#: dura minute. Nu e un termen de raspuns, ci o plasa pentru un flux care nu se mai
#: termina.
OLLAMA_MAX_GENERATION_SECONDS = 300.0
#: Cate generari lasam deodata pe acelasi server. Pe CPU, Ollama le-ar lua oricum pe
#: rand; asteptand aici, termenul primului token masoara modelul, nu coada.
OLLAMA_MAX_PARALLEL = 1
#: Cat asteapta o cerere la coada inainte sa renunte (fara pauza pentru server: nu
#: el a gresit, doar e ocupat).
OLLAMA_QUEUE_TIMEOUT_SECONDS = 180.0
#: Dupa o conexiune picata sau fara primul token, cat timp apelurile cad direct pe template.
OLLAMA_COOLDOWN_SECONDS = 30.0
#: Cat tine Ollama modelul in memorie dupa ultima cerere. Implicitul lui (5 min) il
#: descarca intre doua conversatii, iar reincarcarea pe CPU depaseste singura termenul
#: primului token.
DEFAULT_OLLAMA_KEEP_ALIVE = "30m"
_OLLAMA_PREFIX = "ollama/"

#: Gazda Ollama -> momentul (``time.monotonic``) pana la care nu se mai incearca.
_resting_until: dict[str, float] = {}
_resting_lock = threading.Lock()
#: Gazda Ollama -> cate generari pot rula deodata pe ea.
_gates: dict[str, threading.BoundedSemaphore] = {}
_gates_lock = threading.Lock()


def reset_llm_state() -> None:
    """Uita serverele Ollama gasite oprite si cozile lor - pentru teste."""
    with _resting_lock:
        _resting_until.clear()
    with _gates_lock:
        _gates.clear()


def _gate(host: str, limit: int) -> threading.BoundedSemaphore:
    with _gates_lock:
        gate = _gates.get(host)
        if gate is None:
            gate = _gates[host] = threading.BoundedSemaphore(max(limit, 1))
        return gate


def ollama_model_tag(model: str) -> str:
    """Tag-ul pentru API-ul Ollama: fara prefixul ``ollama/`` (stil LiteLLM, ca in CLI)."""
    model = model.strip()
    return model[len(_OLLAMA_PREFIX) :] if model.lower().startswith(_OLLAMA_PREFIX) else model


class OllamaError(LLMError):
    """Ollama n-a dat un text utilizabil (prea lent, model lipsa, eroare, raspuns gol)."""


class _ThinkingFilter:
    """Scoate rationamentul modelelor care "gandesc" (qwen3, deepseek-r1) dintr-un flux.

    Rationamentul vine primul, intre ``<think>`` si ``</think>``; nimic din el nu
    ajunge la client. Un raspuns fara ``<think>`` la inceput trece neatins.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        #: ``start`` -> ``thinking`` -> ``answer`` (spatiile de dupa rationament se sar)
        #: -> ``text``; sau direct ``start`` -> ``text``.
        self._state: Literal["start", "thinking", "answer", "text"] = "start"

    def feed(self, chunk: str) -> str:
        if self._state == "text":
            return chunk
        self._buffer += chunk
        if self._state == "start":
            head = self._buffer.lstrip()
            if len(head) < len(self._OPEN) and self._OPEN.startswith(head):
                return ""  # inca poate fi inceputul lui <think>
            if not head.startswith(self._OPEN):
                self._state = "text"
                return self._take()
            self._state = "thinking"
        if self._state == "thinking":
            end = self._buffer.find(self._CLOSE)
            if end < 0:
                return ""
            self._buffer = self._buffer[end + len(self._CLOSE) :]
            self._state = "answer"
        self._buffer = self._buffer.lstrip()
        if not self._buffer:
            return ""
        self._state = "text"
        return self._take()

    def flush(self) -> str:
        """Ce a ramas la finalul fluxului; un rationament neinchis nu e raspuns."""
        return self._take() if self._state == "start" else ""

    def _take(self) -> str:
        text, self._buffer = self._buffer, ""
        return text


@dataclass(frozen=True, slots=True)
class OllamaChatClient:
    """Chat cu un model Ollama local - implementeaza ``queen_agent.StreamingTextGenerator``."""

    #: Adresa normalizata (``settings.normalize_ollama_host``), fara ``/`` la final.
    host: str
    model: str = DEFAULT_OLLAMA_MODEL
    connect_timeout: float = OLLAMA_CONNECT_TIMEOUT_SECONDS
    first_token_timeout: float = OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS
    max_generation: float = OLLAMA_MAX_GENERATION_SECONDS
    max_parallel: int = OLLAMA_MAX_PARALLEL
    queue_timeout: float = OLLAMA_QUEUE_TIMEOUT_SECONDS
    #: ``None`` = implicitul serverului Ollama.
    keep_alive: str | None = DEFAULT_OLLAMA_KEEP_ALIVE
    #: Raspunsuri scurte si temperatura mica: formulare, nu creativitate - faptele vin din date.
    max_tokens: int = 450
    temperature: float = 0.3
    #: Samanta fixa: aceeasi intrare da acelasi raspuns si cu temperatura peste 0.
    seed: int | None = None
    cooldown: float = OLLAMA_COOLDOWN_SECONDS
    transport: httpx.BaseTransport | None = None
    clock: Callable[[], float] = time.monotonic

    def complete(
        self,
        *,
        system: str,
        user: str,
        images: Sequence[str] = (),
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        """Raspunsul modelului la cele doua mesaje, intreg (adunat din flux).

        ``images``: imagini base64 atasate mesajului utilizatorului (doar pentru un
        model cu vision). ``schema``: JSON Schema impusa raspunsului (``format`` Ollama).

        Raises:
            LLMUnavailableError: Ollama nu accepta conexiunea (sau n-a raspuns de
                curand - atunci fara sa mai incerce).
            OllamaError: niciun token la timp, generare intrerupta sau raspuns gol.
        """
        text = "".join(
            self.stream(system=system, user=user, images=images, schema=schema)
        ).strip()
        if not text:
            raise OllamaError("Ollama a întors un mesaj gol")
        return text

    def stream(
        self,
        *,
        system: str,
        user: str,
        images: Sequence[str] = (),
        schema: Mapping[str, Any] | None = None,
    ) -> Iterator[str]:
        """Raspunsul modelului, fragment cu fragment, pe masura ce il genereaza.

        Nimic nu pleaca spre server pana la primul ``next()``. Erorile vin din
        iterator: inainte de primul fragment (server oprit, niciun token la timp) sau
        pe parcurs (generare blocata sau intrerupta) - apelantul decide ce face cu ce
        a primit deja.

        Raises:
            LLMUnavailableError: Ollama nu accepta conexiunea (sau e in pauza).
            OllamaError: niciun token in :attr:`first_token_timeout`, coada prea
                lunga, eroare de la server, flux intrerupt.
        """
        if self._resting():
            raise LLMUnavailableError(
                f"Ollama nu a răspuns de curând la {self.host} - reîncerc după pauză"
            )
        gate = _gate(self.host, self.max_parallel)
        if not gate.acquire(timeout=self.queue_timeout):
            raise OllamaError(
                f"Ollama e ocupat cu alte generări de peste {self.queue_timeout:.0f} s"
            )
        try:
            # Cat a stat la coada, cererea din fata poate sa fi pus serverul in pauza.
            if self._resting():
                raise LLMUnavailableError(
                    f"Ollama nu a răspuns de curând la {self.host} - reîncerc după pauză"
                )
            yield from self._generate(system, user, images, schema)
        finally:
            gate.release()

    def _generate(
        self,
        system: str,
        user: str,
        images: Sequence[str] = (),
        schema: Mapping[str, Any] | None = None,
    ) -> Iterator[str]:
        user_message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            user_message["images"] = list(images)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, user_message],
            "stream": True,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        if schema is not None:
            payload["format"] = dict(schema)
        if self.seed is not None:
            payload["options"]["seed"] = self.seed
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        # Termenul de citire e si termenul primului token: raspunsul incepe cu el.
        timeout = httpx.Timeout(self.first_token_timeout, connect=self.connect_timeout)
        started = self.clock()
        thinking = _ThinkingFilter()
        first_token = False
        done = False
        try:
            with (
                httpx.Client(transport=self.transport, timeout=timeout) as client,
                client.stream("POST", f"{self.host}/api/chat", json=payload) as response,
            ):
                if response.status_code != 200:
                    response.read()
                    raise self._status_error(response)
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    content, done = self._chunk(line)
                    elapsed = self.clock() - started
                    if content:
                        first_token = True
                        visible = thinking.feed(content)
                        if visible:
                            yield visible
                    elif not first_token and elapsed > self.first_token_timeout:
                        raise self._no_first_token()
                    if done:
                        break
                    if elapsed > self.max_generation:
                        raise OllamaError(
                            f"Ollama nu a terminat în {self.max_generation:.0f} s"
                        )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self._rest()
            raise LLMUnavailableError(
                f"Ollama nu răspunde la {self.host} ({type(exc).__name__}): pornește-l cu "
                "«ollama serve» sau corectează OLLAMA_HOST"
            ) from exc
        except httpx.TimeoutException as exc:
            if not first_token:
                raise self._no_first_token() from exc
            raise OllamaError(
                f"Ollama s-a oprit în mijlocul răspunsului (nimic nou în "
                f"{self.first_token_timeout:.0f} s)"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama nu a răspuns ({type(exc).__name__})") from exc
        if not done:
            raise OllamaError("Ollama a întrerupt generarea înainte de final")
        tail = thinking.flush()
        if tail:
            yield tail

    def _chunk(self, line: str) -> tuple[str, bool]:
        """Un rand NDJSON din flux -> ``(text, done)``."""
        try:
            chunk = json.loads(line)
        except ValueError as exc:
            raise OllamaError("Ollama a întors un răspuns neașteptat (nu e JSON)") from exc
        if not isinstance(chunk, dict):
            raise OllamaError("Ollama a întors un răspuns neașteptat")
        if chunk.get("error"):
            raise OllamaError(f"Ollama a întrerupt generarea: {str(chunk['error'])[:200]}")
        message = chunk.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        done = chunk.get("done") is True
        if not isinstance(content, str):
            if not done:
                raise OllamaError("Ollama a întors un răspuns neașteptat")
            content = ""
        return content, done

    def _status_error(self, response: httpx.Response) -> OllamaError:
        if response.status_code == 404:
            return OllamaError(
                f"Ollama a răspuns 404: {_error_detail(response)} - dacă lipsește modelul: "
                f"ollama pull {self.model}"
            )
        return OllamaError(f"Ollama a răspuns {response.status_code}: {_error_detail(response)}")

    def _no_first_token(self) -> OllamaError:
        # Masina e prea lenta pentru model (sau inca il incarca): urmatoarele apeluri ar
        # astepta la fel - sinteza consiliului, dupa membri, cade direct pe template.
        self._rest()
        return OllamaError(
            f"Ollama n-a trimis niciun token în {self.first_token_timeout:.0f} s (modelul "
            f"«{self.model}» poate fi prea mare pentru mașină)"
        )

    def _resting(self) -> bool:
        with _resting_lock:
            return self.clock() < _resting_until.get(self.host, -math.inf)

    def _rest(self) -> None:
        with _resting_lock:
            _resting_until[self.host] = self.clock() + self.cooldown


# --- ruterul -------------------------------------------------------------------------

TaskType = Literal["classify", "score", "verify", "generate"]
Backend = Literal["jev", "ollama"]
#: Unde merge fiecare sarcina: deciziile la Sistemul 1, textul la Sistemul 2.
ROUTES: Mapping[TaskType, Backend] = {
    "classify": "jev",
    "score": "jev",
    "verify": "jev",
    "generate": "ollama",
}


class LLMRouter:
    """Trimite fiecare sarcina la sistemul ei (:data:`ROUTES`).

    E si vocea Reginei si a consiliului (``StreamingTextGenerator``): ``complete`` trece
    prin :meth:`generate_text_local`, ``stream`` prin :meth:`stream_text_local`, deci orice
    text generat ajunge doar la Ollama.
    """

    def __init__(
        self, *, jev: JevClient | None = None, ollama: OllamaChatClient | None = None
    ) -> None:
        self._jev = jev
        self._ollama = ollama

    @staticmethod
    def backend(task: TaskType) -> Backend:
        return ROUTES[task]

    def ready(self, task: TaskType) -> bool:
        """Sistemul sarcinii e configurat (nu garanteaza ca si raspunde)."""
        client = self._jev if ROUTES[task] == "jev" else self._ollama
        return client is not None

    @property
    def voice(self) -> LLMRouter | None:
        """Ruterul, ca voce - sau ``None`` fara Ollama (-> template-uri)."""
        return self if self.ready("generate") else None

    # Sistemul 1 ----------------------------------------------------------------------

    def _system_one(
        self, task: TaskType, state: JsonValue, questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        if ROUTES[task] != "jev" or self._jev is None:
            raise LLMUnavailableError(f"Jev nu e configurat (JEV_API_KEY) pentru «{task}»")
        return self._jev.system_one(state, questions)

    def jev_classify(self, state: JsonValue, question: Choice) -> ChoiceAnswer:
        """Choice: ce optiune se potriveste ``state``-ului."""
        answers = self._system_one("classify", state, {"choice": question})
        return _typed("choice", answers["choice"], ChoiceAnswer)

    def jev_score(
        self, state: JsonValue, questions: Mapping[str, Score]
    ) -> dict[str, ScoreAnswer]:
        """Score: mai multe scari pe acelasi ``state``, intr-o singura cerere."""
        answers = self._system_one("score", state, questions)
        return {qid: _typed(qid, answer, ScoreAnswer) for qid, answer in answers.items()}

    def jev_verify(self, state: JsonValue, question: Noul, *, threshold: float = YES) -> bool:
        """Noul: e adevarat ce intreaba ``question`` despre ``state``? (``noul >= threshold``)."""
        answers = self._system_one("verify", state, {"verify": question})
        return _typed("verify", answers["verify"], NoulAnswer).yes(threshold)

    # Sistemul 2 ----------------------------------------------------------------------

    def _local(self) -> OllamaChatClient:
        if ROUTES["generate"] != "ollama" or self._ollama is None:
            raise LLMUnavailableError("Ollama nu e configurat (OLLAMA_HOST gol)")
        return self._ollama

    def generate_text_local(self, *, system: str, user: str) -> str:
        """Textul, generat local de Ollama."""
        return self._local().complete(system=system, user=user)

    def stream_text_local(self, *, system: str, user: str) -> Iterator[str]:
        """Textul, generat local de Ollama, fragment cu fragment (vezi ``OllamaChatClient``)."""
        return self._local().stream(system=system, user=user)

    @property
    def model(self) -> str:
        """Modelul care scrie textul (``TextGenerator``)."""
        return self._ollama.model if self._ollama is not None else ""

    def complete(self, *, system: str, user: str) -> str:
        return self.generate_text_local(system=system, user=user)

    def stream(self, *, system: str, user: str) -> Iterator[str]:
        return self.stream_text_local(system=system, user=user)


def jev_client_from_settings(settings: ServerSettings) -> JevClient | None:
    """Jev din ``.env`` (``None`` fara ``JEV_API_KEY``): TypeSafe direct sau un gateway
    cu acelasi protocol (``JEV_URL``/``JEV_MODEL``, ex. OpenCode Zen)."""
    if not settings.jev_api_key:
        return None
    return JevClient(
        api_key=settings.jev_api_key,
        model=settings.jev_model or DEFAULT_JEV_MODEL,
        url=settings.jev_url or JEV_URL,
    )


def llm_router_from_settings(settings: ServerSettings) -> LLMRouter:
    """Ruterul din ``.env``: fara ``JEV_API_KEY`` nu exista Sistemul 1, fara
    ``OLLAMA_HOST`` nu exista Sistemul 2 - fiecare cade pe regulile lui fixe."""
    jev = jev_client_from_settings(settings)
    ollama = None
    if settings.ollama_host:
        model = ollama_model_tag(settings.ollama_model) or DEFAULT_OLLAMA_MODEL
        ollama = OllamaChatClient(
            host=settings.ollama_host,
            model=model,
            first_token_timeout=settings.ollama_first_token_timeout,
            max_parallel=settings.ollama_max_parallel,
            keep_alive=settings.ollama_keep_alive or None,
        )
    return LLMRouter(jev=jev, ollama=ollama)
