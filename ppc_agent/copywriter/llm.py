"""Clienti de generare de copy, decuplati prin injectie de dependenta.

- :class:`BaseLLMClient` — interfata; ``AdCopyGenerator`` primeste un client prin constructor.
- :class:`MockLLMClient` — determinist, fara retea; randeaza copy emotional pe stilul
  framework-ului recuperat. Testabil acum.
- :class:`LiveLLMClient` — stub pentru un client real (Ollama / API), ridica
  :class:`~ppc_agent.errors.SetupRequiredError` pana la conectare.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from ppc_agent.copywriter.models import AdCopy, CopySpec, char_count
from ppc_agent.errors import SetupRequiredError


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


class LiveLLMClient(BaseLLMClient):
    """Stub pentru un client real (Ollama sau API). Ridica pana la conectare.

    ``spec.system_prompt`` este deja construit de :class:`AdCopyGenerator` cu
    framework-ul injectat; o implementare reala doar il trimite modelului impreuna
    cu un user prompt si parseaza JSON-ul returnat.
    """

    def __init__(self, model: str = "neconfigurat") -> None:
        self._model = model

    def generate(self, spec: CopySpec) -> AdCopy:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        raise SetupRequiredError(
            "client LLM live neimplementat. Ruleaza cu MockLLMClient sau conecteaza "
            f"un client Ollama/API (model tinta configurat: {self._model})."
        )
