"""``AdCopyGenerator`` — genereaza copy emotional, cu cuvantul cheie fortat in headline.

Fluxul:

1. recupereaza framework-ul dupa declansatorul emotional (RAG local peste swipe file)
2. construieste un system prompt cu structura framework-ului injectata
3. cere clientului (mock sau live) sa genereze
4. forteaza cuvantul cheie exact intr-un headline
5. valideaza limitele Google Ads; la depasire, reincearca mai concis, apoi esueaza clar
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ppc_agent.copywriter.llm import BaseLLMClient
from ppc_agent.copywriter.models import (
    DESCRIPTION_LIMIT,
    HEADLINE_LIMIT,
    AdCopy,
    CopySpec,
    Framework,
    TikTokAdCopy,
    TikTokCopySpec,
    TikTokSwipeRecord,
    char_count,
)
from ppc_agent.copywriter.swipe import (
    default_swipe_path,
    load_swipe_file,
    retrieve_framework,
    retrieve_tiktok_examples,
)
from ppc_agent.errors import AdsLimitError, CopywriterError
from ppc_agent.texttools import contains_phrase

_MAX_ATTEMPTS = 4
Platform = Literal["google", "tiktok"]


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


def build_tiktok_system_prompt(examples: list[TikTokSwipeRecord]) -> str:
    """Construieste system prompt-ul pentru scripturi TikTok, cu exemple RAG injectate.

    Persona: creator de continut nativ, nu copywriter corporate. Ritmul (fereastra
    de hook, structura, durata) e ancorat in cercetare reala despre reclame TikTok
    cu conversie mare (hook 1.5-3s = intrerupere de tipar, apoi problema -> dovada
    -> CTA nativ, scenariu vorbit de 15-30s). Schema ceruta e generata direct din
    ``TikTokAdCopy.model_json_schema()`` ca sa ramana sincronizata cu clasa.
    """
    schema_types = {
        name: prop.get("type", "string")
        for name, prop in TikTokAdCopy.model_json_schema()["properties"].items()
    }
    example_lines = (
        "\n".join(
            f'  - [{example.niche}, activ {example.days_active_proxy} zile] '
            f'hook: "{example.hook_audio}" | dovada: "{example.mechanism_proof}" | '
            f'cta: "{example.cta_text}"'
            for example in examples
        )
        or "  (niciun exemplu recuperat - improvizeaza in stilul UGC TikTok)"
    )
    return (
        "Esti creator de continut nativ TikTok, nu un copywriter corporate. Scrii "
        "scripturi video verticale (9:16) in limba romana, conversationale, "
        "energice, ca pentru propriul tau canal — zero limbaj corporate, zero "
        "superlative goale.\n\n"
        "RITM OBLIGATORIU:\n"
        "- primele 1.5-3 secunde (audio_hook): intrerupere de tipar - opreste "
        "scrollul, nu introduce contextul incet\n"
        "- restul (body_script): numeste problema, agit-o pe scurt, arata "
        "solutia / dovada ca functioneaza\n"
        "- ultimele 3-5 secunde (call_to_action): CTA nativ platformei, scurt\n"
        "- durata totala vizata a scenariului vorbit: 15-30 secunde\n\n"
        "EXEMPLE DOVEDITE (din biblioteca proprie, nu copia — inspira-te din ritm):\n"
        f"{example_lines}\n\n"
        "REGULI STRICTE:\n"
        "- fara jargon corporate, fara propozitii lungi si formale\n"
        "- text_overlay: 2-4 fraze scurte (sub-titrari dinamice), nu propozitii intregi\n"
        "- alege creative_angle descriptiv (ex. contrarian_warning, problem_solution, "
        "ugc_unboxing, objection_first, mistake_opener)\n"
        f"- raspunde DOAR cu JSON, exact campurile: {json.dumps(schema_types, ensure_ascii=False)}"
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
        self,
        product_usp: str,
        target_keyword: str,
        emotion_trigger: str,
        platform: Platform = "google",
    ) -> dict[str, Any]:
        """Genereaza copy pentru un anunt si il returneaza strict ca dict.

        Args:
            product_usp: Propunerea unica de valoare a produsului / serviciului.
            target_keyword: Cuvantul cheie exact-match (Google) / nisa tinta (TikTok).
            emotion_trigger: Declansatorul emotional (``"frica"``, ``"status"``,
                ``"fomo"``, sau o descriere).
            platform: ``"google"`` (implicit, comportament neschimbat: headline/desc
                cu retry pe limite) sau ``"tiktok"`` (script video, RAG pe nisa/cuvant
                cheie peste ``tiktok_swipe_library``, fara retry — limitele Google nu
                se aplica).

        Returns:
            Pentru ``google``: ``{"headline_1", "headline_2", "description"}``.
            Pentru ``tiktok``: campurile :class:`~ppc_agent.copywriter.models.TikTokAdCopy`
            (``text_overlay`` e o lista, deci tipul de returnare e ``dict[str, Any]``).

        Raises:
            SwipeFileError: Daca declansatorul/nisa nu se potriveste cu nimic
                (google), sau ``tiktok_swipe_library`` e goala (tiktok).
            AdsLimitError: Google, daca dupa toate incercarile tot depaseste limitele.
            CopywriterError: Cuvantul cheie e mai lung decat limita de headline
                (google), sau raspunsul clientului nu respecta schema (ambele).
        """
        keyword = " ".join(target_keyword.split())

        if platform == "tiktok":
            examples = retrieve_tiktok_examples(self._swipe, keyword)
            system_prompt = build_tiktok_system_prompt(examples)
            tiktok_spec = TikTokCopySpec(
                product_usp=product_usp,
                target_keyword=keyword,
                emotion_trigger=emotion_trigger,
                examples=examples,
                system_prompt=system_prompt,
            )
            tiktok_ad = self._client.generate_tiktok(tiktok_spec)
            return tiktok_ad.as_dict()

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
