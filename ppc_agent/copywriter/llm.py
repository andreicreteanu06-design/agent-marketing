"""Clienti de generare de copy, decuplati prin injectie de dependenta.

- :class:`BaseLLMClient` — interfata; ``AdCopyGenerator`` primeste un client prin constructor.
- :class:`MockLLMClient` — determinist, fara retea; randeaza copy emotional pe stilul
  framework-ului recuperat. Testabil acum.
- :class:`LiveLLMClient` — client real pentru un model Ollama local (gratuit, datele
  nu parasesc masina). E singurul apel de retea din tot agentul, dar ramane
  loopback (``localhost``); daca Ollama nu ruleaza sau modelul nu e descarcat,
  ridica :class:`~ppc_agent.errors.SetupRequiredError` cu instructiuni concrete.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from ppc_agent.copywriter.models import AdCopy, CopySpec, char_count
from ppc_agent.errors import CopywriterError, SetupRequiredError


class BaseLLMClient(ABC):
    """Interfata unui client care produce :class:`AdCopy` dintr-un :class:`CopySpec`."""

    @abstractmethod
    def generate(self, spec: CopySpec) -> AdCopy:
        """Genereaza copy conform ``spec``.

        Implementarea trebuie sa returneze un :class:`AdCopy`; nu e obligata sa
        respecte limitele Google Ads (validarea + retry-ul se fac in
        :class:`~ppc_agent.copywriter.engine.AdCopyGenerator`).
        """


def _stable_index(seed: str, modulo: int) -> int:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, modulo)


def _fit(text: str, limit: int) -> str:
    """Scurteaza ``text`` la ``limit`` caractere, taind la granita de cuvant."""
    text = " ".join(text.split()).strip(" -,.;")
    if char_count(text) <= limit:
        return text
    words = text.split(" ")
    out = ""
    for word in words:
        candidate = word if not out else f"{out} {word}"
        if char_count(candidate) > limit:
            break
        out = candidate
    return (out or text[:limit]).strip(" -,.;")


def _titlecase_keyword(keyword: str) -> str:
    cleaned = " ".join(keyword.split())
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


def _compose_description(usp: str, tail: str, limit: int, *, tighten: int) -> str:
    """Cea mai lunga combinatie de propozitii intregi care incape in ``limit``.

    Evita taierea la mijloc de propozitie: intai USP + coada emotionala, apoi doar
    USP, apoi USP scurtat ca ultima solutie.
    """
    usp_sentence = f"{usp.rstrip('.')}."
    if tighten == 0:
        full = f"{usp.rstrip('.')}. {tail}"
        if char_count(full) <= limit:
            return full
    if char_count(usp_sentence) <= limit:
        return usp_sentence
    return _fit(usp, limit)


# Banci de fraze emotionale per stil (H2 + coada descrierii). Fara aleator.
_H2_BANK: dict[str, tuple[str, ...]] = {
    "pas": (
        "Ignori acum, platesti dublu",
        "Micile semne devin facturi mari",
        "O reparatie < o piesa noua",
        "Nu lasa sa se agraveze",
    ),
    "status": (
        "Toti vor intreba de unde e",
        "Eleganta care se remarca",
        "Detaliul care schimba tinuta",
        "Se vede ca ai gust",
    ),
    "fomo": (
        "Se termina rapid",
        "Pretul creste luni",
        "Ultimele bucati din stoc",
        "Oferta expira curand",
    ),
    "aida": (
        "Rezultate, nu promisiuni",
        "Simplu de la primul click",
        "Configurezi in 5 minute",
        "Fara card la inregistrare",
    ),
}

_DESC_TAIL: dict[str, str] = {
    "pas": "Verifica azi, nu astepta sa fie prea tarziu.",
    "status": "Prietenii vor crede ca ai dat o avere.",
    "fomo": "Rezerva acum, maine poate fi prea tarziu.",
    "aida": "Vezi singur diferenta - incepe gratuit azi.",
}


class MockLLMClient(BaseLLMClient):
    """Generator determinist care randeaza copy pe stilul framework-ului.

    Nu e un LLM: umple sabloane emotionale modelate dupa ``example_ad`` cu USP-ul
    si cuvantul cheie. Serveste ca implementare de referinta si pentru teste;
    se inlocuieste cu un client real prin aceeasi interfata.
    """

    def generate(self, spec: CopySpec) -> AdCopy:
        """Randeaza :class:`AdCopy` determinist din ``spec``."""
        style = spec.framework.style
        keyword_title = _titlecase_keyword(spec.target_keyword)
        usp = " ".join(spec.product_usp.split()).rstrip(".")

        h2_bank = _H2_BANK[style]
        h2 = h2_bank[_stable_index(f"{spec.target_keyword}|{style}", len(h2_bank))]

        # H1: cuvantul cheie exact, cu un cadru emotional daca incape.
        frames = {
            "pas": f"{keyword_title}?",
            "status": f"{keyword_title} cu stil",
            "fomo": f"{keyword_title} - stoc redus",
            "aida": keyword_title,
        }
        headline_limit = spec.headline_limit
        if spec.tighten > 0:
            headline_1 = _fit(keyword_title, headline_limit)
            h2 = _fit(h2, headline_limit)
        else:
            framed = frames[style]
            headline_1 = (
                framed
                if char_count(framed) <= headline_limit
                else _fit(keyword_title, headline_limit)
            )

        description = _compose_description(
            usp, _DESC_TAIL[style], spec.description_limit, tighten=spec.tighten
        )

        return AdCopy(
            headline_1=headline_1,
            headline_2=_fit(h2, headline_limit),
            description=description,
        )


_DEFAULT_ENDPOINT = "http://localhost:11434"
_DEFAULT_TIMEOUT = 60.0
_OLLAMA_PREFIX = "ollama/"


def _normalize_model_tag(model: str) -> str:
    """Elimina prefixul stil-LiteLLM ``ollama/`` — API-ul Ollama vrea doar tag-ul."""
    if model.lower().startswith(_OLLAMA_PREFIX):
        return model[len(_OLLAMA_PREFIX) :]
    return model


def _build_user_prompt(spec: CopySpec) -> str:
    """User prompt-ul trimis modelului; cere explicit mai putina lungime la retry."""
    lines = [
        f"Cuvant cheie exact: {spec.target_keyword}",
        f"USP produs/serviciu: {spec.product_usp}",
        f"Declansator emotional: {spec.emotion_trigger}",
    ]
    if spec.tighten > 0:
        lines.append(
            "Incercarea anterioara a fost prea lunga - fii mai concis, taie orice "
            "cuvant care nu e strict necesar."
        )
    lines.append(
        'Raspunde DOAR cu JSON: {"headline_1": "...", "headline_2": "...", '
        '"description": "..."}'
    )
    return "\n".join(lines)


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

    Nu e nevoie de cheie API si niciun text nu paraseste masina — e loopback pur.
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

    @property
    def num_gpu(self) -> int | None:
        """Suprascrierea ``num_gpu`` (``None`` = Ollama decide singur)."""
        return self._num_gpu

    def generate(self, spec: CopySpec) -> AdCopy:
        """Cere modelului Ollama copy conform ``spec``; parseaza JSON-ul returnat.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar continutul nu e JSON valid cu
                campurile asteptate.
        """
        options: dict[str, Any] = {"temperature": 0.6}
        if self._num_gpu is not None:
            options["num_gpu"] = self._num_gpu
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": _build_user_prompt(spec)},
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
                "sau corecteaza PPC_LLM_ENDPOINT in .env."
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
            raise CopywriterError(
                f"Ollama a raspuns cu eroarea {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
            if data.get("done") is False:
                raise CopywriterError(
                    f"Ollama a intrerupt generarea pentru '{self._model}' inainte de a "
                    "termina raspunsul (posibil model corupt sau incarcare esuata). "
                    "Verifica 'ollama ps' si log-urile serverului, sau redescarca-l: "
                    f"ollama pull {self._model}"
                )
            content = data["message"]["content"]
            parsed = json.loads(content)
            return AdCopy.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid cu campurile "
                f"asteptate (headline_1/headline_2/description): {exc}"
            ) from exc
