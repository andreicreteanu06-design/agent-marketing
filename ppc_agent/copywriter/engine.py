"""``AdCopyGenerator`` — genereaza copy emotional, cu cuvantul cheie fortat in headline.

Fluxul:

1. recupereaza framework-ul dupa declansatorul emotional (RAG local peste swipe file)
2. construieste un system prompt cu structura framework-ului injectata
3. cere clientului (mock sau live) sa genereze
4. forteaza cuvantul cheie exact intr-un headline
5. valideaza limitele Google Ads; la depasire, reincearca mai concis, apoi esueaza clar
"""

from __future__ import annotations

from pathlib import Path

from ppc_agent.copywriter.llm import BaseLLMClient
from ppc_agent.copywriter.models import (
    DESCRIPTION_LIMIT,
    HEADLINE_LIMIT,
    AdCopy,
    CopySpec,
    Framework,
    char_count,
)
from ppc_agent.copywriter.swipe import (
    default_swipe_path,
    load_swipe_file,
    retrieve_framework,
)
from ppc_agent.errors import AdsLimitError, CopywriterError
from ppc_agent.texttools import contains_phrase

_MAX_ATTEMPTS = 4


def check_google_limits(
    ad: AdCopy,
    *,
    headline_limit: int = HEADLINE_LIMIT,
    description_limit: int = DESCRIPTION_LIMIT,
) -> None:
    """Ridica :class:`AdsLimitError` daca un camp depaseste limita Google Ads.

    Numararea foloseste caractere normalizate NFC (ca Google Ads).

    Args:
        ad: Copy-ul de verificat.
        headline_limit: Limita pentru headline-uri (implicit 30).
        description_limit: Limita pentru descriere (implicit 90).

    Raises:
        AdsLimitError: La prima depasire gasita.
    """
    for field, limit in (
        ("headline_1", headline_limit),
        ("headline_2", headline_limit),
        ("description", description_limit),
    ):
        length = char_count(getattr(ad, field))
        if length > limit:
            raise AdsLimitError(field, length, limit)


def build_system_prompt(
    framework: Framework, headline_limit: int, description_limit: int
) -> str:
    """Construieste system prompt-ul, cu structura framework-ului injectata.

    Folosit ca atare de un client LLM real; ``MockLLMClient`` il ignora semantic
    dar structura este deja pregatita pentru inlocuire.
    """
    example = framework.example_ad
    return (
        "Esti copywriter de direct-response. Scrii copy pentru Google Ads cu "
        "incarcatura emotionala, concret si direct. Eviti limbajul corporate, "
        "clisee si superlativele goale.\n\n"
        f"FRAMEWORK: {framework.name}\n"
        f"DECLANSATOR: {framework.trigger}\n"
        f"STRUCTURA: {framework.structure}\n\n"
        "EXEMPLU (respecta tonul si tiparul, nu copia):\n"
        f"  H1: {example.headline_1}\n"
        f"  H2: {example.headline_2}\n"
        f"  Descriere: {example.description}\n\n"
        "REGULI STRICTE:\n"
        f"- headline_1 si headline_2: maxim {headline_limit} caractere fiecare\n"
        f"- description: maxim {description_limit} caractere\n"
        "- cuvantul cheie exact trebuie sa apara intr-un headline\n"
        '- raspunde DOAR cu JSON: {"headline_1": ..., "headline_2": ..., "description": ...}'
    )


class AdCopyGenerator:
    """Genereaza copy emotional pentru un cuvant cheie, cu un client injectat."""

    def __init__(
        self, llm_client: BaseLLMClient, swipe_path: Path | str | None = None
    ) -> None:
        """Creeaza generatorul.

        Args:
            llm_client: Clientul de generare (``MockLLMClient`` sau, ulterior, unul real).
            swipe_path: Cale catre ``swipe_file.json``; implicit radacina proiectului.
        """
        self._client = llm_client
        self._swipe = load_swipe_file(swipe_path or default_swipe_path())

    @property
    def swipe_styles(self) -> list[str]:
        """Stilurile de framework disponibile in swipe file."""
        return self._swipe.styles()

    def generate_emotional_copy(
        self, product_usp: str, target_keyword: str, emotion_trigger: str
    ) -> dict[str, str]:
        """Genereaza copy pentru un anunt si il returneaza strict ca dict.

        Args:
            product_usp: Propunerea unica de valoare a produsului / serviciului.
            target_keyword: Cuvantul cheie exact-match (fortat intr-un headline).
            emotion_trigger: Declansatorul emotional (``"frica"``, ``"status"``,
                ``"fomo"``, sau o descriere).

        Returns:
            ``{"headline_1": "...", "headline_2": "...", "description": "..."}``.

        Raises:
            SwipeFileError: Daca declansatorul nu se potriveste cu niciun framework.
            AdsLimitError: Daca dupa toate incercarile copy-ul tot depaseste limitele.
            CopywriterError: Daca cuvantul cheie e mai lung decat limita de headline.
        """
        keyword = " ".join(target_keyword.split())
        if char_count(keyword) > HEADLINE_LIMIT:
            raise CopywriterError(
                f"cuvantul cheie '{keyword}' are {char_count(keyword)} caractere si "
                f"nu incape intr-un headline de {HEADLINE_LIMIT}"
            )

        framework = retrieve_framework(self._swipe, emotion_trigger)
        system_prompt = build_system_prompt(
            framework, HEADLINE_LIMIT, DESCRIPTION_LIMIT
        )

        last_error: AdsLimitError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            spec = CopySpec(
                product_usp=product_usp,
                target_keyword=keyword,
                emotion_trigger=emotion_trigger,
                framework=framework,
                system_prompt=system_prompt,
                tighten=attempt,
            )
            ad = _force_keyword(self._client.generate(spec), keyword)
            try:
                check_google_limits(ad)
            except AdsLimitError as exc:
                last_error = exc
                continue
            return ad.as_dict()

        if last_error is None:  # pragma: no cover - bucla ruleaza mereu
            raise CopywriterError("generarea de copy a esuat fara un motiv clar")
        raise last_error


def _force_keyword(ad: AdCopy, keyword: str) -> AdCopy:
    """Garanteaza ca ``keyword`` apare intr-un headline (fara sa depaseasca limita)."""
    if contains_phrase(ad.headline_1, keyword) or contains_phrase(
        ad.headline_2, keyword
    ):
        return ad
    keyword_title = keyword[:1].upper() + keyword[1:]
    if char_count(keyword_title) <= HEADLINE_LIMIT:
        return ad.model_copy(update={"headline_1": keyword_title})
    return ad
