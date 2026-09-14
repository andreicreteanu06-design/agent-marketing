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

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.copywriter.knowledge_loader import (
    MarketingKnowledgeBase,
    default_knowledge_base_path,
    frameworks_for_objective,
    load_knowledge_base,
    render_frameworks,
)
from ppc_agent.copywriter.llm import BaseLLMClient
from ppc_agent.copywriter.models import (
    DESCRIPTION_LIMIT,
    HEADLINE_LIMIT,
    AdCopy,
    CopySpec,
    Framework,
    OmniAdCopy,
    OmniCopySpec,
    OmniPlatform,
    OmniSwipeRecord,
    StoryboardSpec,
    TikTokAdCopy,
    TikTokCopySpec,
    TikTokSwipeRecord,
    char_count,
)
from ppc_agent.copywriter.prompts import ART_DIRECTOR_INSTRUCTIONS, STORYBOARD_FORMAT_EXAMPLE
from ppc_agent.copywriter.swipe import (
    default_swipe_path,
    load_swipe_file,
    retrieve_framework,
    retrieve_omnichannel_examples,
    retrieve_tiktok_examples,
)
from ppc_agent.creative.video_models import Storyboard
from ppc_agent.creative.video_qa import StoryboardValidator
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


_OBJECTIVE_GUIDANCE: dict[CampaignObjective, str] = {
    CampaignObjective.SALES: (
        "OBIECTIV: SALES (conversie tranzactionala directa, e-commerce).\n"
        '- CTA tranzactional: "Adauga in cos", "Cumpara acum", "Stoc limitat"\n'
        "- focus pe actiunea imediata de cumparare, nu pe o discutie prealabila"
    ),
    CampaignObjective.LEAD_GEN: (
        "OBIECTIV: LEAD_GEN (captarea unui contact, nu o vanzare instantanee).\n"
        '- CTA consultativ: "Programeaza o consultatie", "Cere o oferta", "Suna acum"\n'
        "- focus pe obtinerea datelor de contact sau a unui apel telefonic"
    ),
}


def build_objective_guidance(objective: CampaignObjective) -> str:
    """Instructiunea de CTA/focus dupa obiectivul clientului - niciodata ghicit,
    vine din ``ClientAccount.objective`` si se injecteaza in orice system
    prompt de mai jos (nu duplica logica de framework/RAG, doar o completeaza).
    """
    return _OBJECTIVE_GUIDANCE[objective]


def build_marketing_psychology_guidance(
    knowledge_base: MarketingKnowledgeBase, objective: CampaignObjective
) -> str:
    """Principii de persuasiune consacrate (vezi ``copywriter/knowledge_loader.py``),
    relevante obiectivului - completeaza :func:`build_objective_guidance` (stil de
    CTA) cu tehnici concrete de folosit in corpul textului, nu doar in CTA.
    """
    principles = frameworks_for_objective(knowledge_base, objective)
    return "PRINCIPII DE PERSUASIUNE DE FOLOSIT:\n" + render_frameworks(principles)


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
        "- cele doua headline-uri trebuie sa aiba sens separat SI impreuna - "
        "Google Ads le poate combina automat in orice ordine (Responsive Search Ads)\n"
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


_OMNI_PLATFORM_GUIDANCE: dict[str, str] = {
    "google": (
        "Google Ads (Search/YouTube): limite stricte de caractere, intentie de "
        "cautare ridicata - raspunzi direct la ce cauta cineva chiar acum, "
        "garantii clare, text simplu si direct, fara poveste lunga."
    ),
    "meta": (
        "Meta Ads (Facebook/Instagram): formate cu longevitate dovedita (o "
        "reclama care ruleaza de saptamani nu se opreste din intamplare), stil "
        "advertorial de povestire, hook emotional, corp de text mai lung - "
        "cititorul deruleaza feed-ul, trebuie oprit cu o poveste, nu doar un titlu."
    ),
    "tiktok": (
        "TikTok Ads: hook audio/vizual in primele 3 secunde, intrerupere de "
        "tipar (pattern interrupt), ritm rapid, scenariu vorbit stil UGC nativ, "
        "zero limbaj corporate."
    ),
}


def build_omnichannel_system_prompt(
    target_platform: OmniPlatform, examples: list[OmniSwipeRecord]
) -> str:
    """Construieste system prompt-ul omnicanal, cu ghidaj dinamic per platforma.

    Spre deosebire de :func:`build_tiktok_system_prompt` (un singur canal),
    aici tonul si structura variaza dupa ``target_platform`` — vezi
    ``_OMNI_PLATFORM_GUIDANCE``. Exemplele injectate sunt deja filtrate pe
    platforma (vezi :func:`~ppc_agent.copywriter.swipe.retrieve_omnichannel_examples`)
    si validate prin semnale proxy (longevitate, numar de variante), nu prin ROI
    auto-raportat. Schema ceruta e generata direct din
    ``OmniAdCopy.model_json_schema()`` ca sa ramana sincronizata cu clasa.
    """
    schema_types = {
        name: prop.get("type", "string")
        for name, prop in OmniAdCopy.model_json_schema()["properties"].items()
    }
    example_lines = (
        "\n".join(
            f'  - [{example.niche}, {example.performance_signal}] '
            f'hook ({example.hook_type}): "{example.hook_text}" | '
            f'problema: "{example.problem_agitation}" | '
            f'dovada: "{example.mechanism_proof}" | cta: "{example.offer_cta}"'
            for example in examples
        )
        or "  (niciun exemplu recuperat pentru aceasta platforma - improvizeaza in ton)"
    )
    return (
        "Esti copywriter de direct-response, expert in reclame platite pe mai "
        "multe canale. Scrii concret, fara clisee, fara superlative goale.\n\n"
        f"PLATFORMA: {target_platform.upper()}\n"
        f"GHIDAJ: {_OMNI_PLATFORM_GUIDANCE[target_platform]}\n\n"
        "EXEMPLE DOVEDITE (nu copia - inspira-te din structura si ritm; validate "
        "prin longevitate si numar de variante active, nu prin ROI auto-raportat):\n"
        f"{example_lines}\n\n"
        "REGULI STRICTE:\n"
        "- hook_type: eticheta scurta a tipului de hook (ex. pattern_interrupt, "
        "relatable_pain_point, specific_number, high_intent_question)\n"
        "- problem_agitation: numeste + adanceste problema, nu doar o mentioneaza\n"
        "- mechanism_proof: de ce functioneaza solutia, concret, nu vag\n"
        f"- raspunde DOAR cu JSON, exact campurile: {json.dumps(schema_types, ensure_ascii=False)}"
    )


def build_storyboard_system_prompt(examples: list[TikTokSwipeRecord]) -> str:
    """Construieste system prompt-ul pentru storyboard-uri video programatice.

    Spre deosebire de :func:`build_tiktok_system_prompt` (script plat: hook/
    body/cta ca text), aici LLM-ul e Lead Performance Creative Director - iese
    un :class:`~ppc_agent.creative.video_models.Storyboard` cu scene
    cronometrate, text pozitionat in zone sigure si piste audio separate,
    productie-ready. Regulile de regie vin din ``ART_DIRECTOR_INSTRUCTIONS``;
    formatul cerut e un exemplu construit din instantierea reala a modelelor
    (``STORYBOARD_FORMAT_EXAMPLE``) - nu poate deveni tacit inconsistent cu
    schema (vezi ``copywriter/prompts.py``).
    """
    example_lines = (
        "\n".join(
            f'  - [{example.niche}, activ {example.days_active_proxy} zile] '
            f'hook: "{example.hook_audio}" | dovada: "{example.mechanism_proof}" | '
            f'cta: "{example.cta_text}"'
            for example in examples
        )
        or "  (niciun exemplu recuperat - improvizeaza in stilul UGC TikTok)"
    )
    example_json = json.dumps(
        STORYBOARD_FORMAT_EXAMPLE.model_dump(), ensure_ascii=False, indent=2
    )
    return (
        "Esti Lead Performance Creative Director - regizezi reclame video "
        "scurte (9:16, 1080x1920, 30fps) ca pentru productie reala, nu doar "
        "scrii text de citit.\n\n"
        f"{ART_DIRECTOR_INSTRUCTIONS}\n\n"
        "EXEMPLE DOVEDITE DIN BIBLIOTECA (nu copia continutul - inspira-te din "
        "ritm si structura):\n"
        f"{example_lines}\n\n"
        "REGULI STRICTE DE FORMAT:\n"
        "- duration_seconds <= 30\n"
        "- fiecare scena: end_time > start_time, fara goluri neasteptate intre scene\n"
        "- caption-uri (text_layers de tip 'caption'): 24-32 caractere, durata "
        "minima 0.9 secunde (ideal 1.5)\n"
        "- un overlay de tip 'cta' trebuie sa apara in ultimele 3-6 secunde ale "
        "video-ului si sa ramana vizibil minimum 2.0 secunde\n"
        "- raspunde DOAR cu JSON valid, EXACT aceasta structura (doar formatul, "
        "nu continutul din exemplu):\n"
        f"{example_json}"
    )


class AdCopyGenerator:
    """Genereaza copy emotional pentru un cuvant cheie, cu un client injectat."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        swipe_path: Path | str | None = None,
        knowledge_base_path: Path | str | None = None,
    ) -> None:
        """Creeaza generatorul.

        Args:
            llm_client: Clientul de generare (``MockLLMClient`` sau, ulterior, unul real).
            swipe_path: Cale catre ``swipe_file.json``; implicit radacina proiectului.
            knowledge_base_path: Cale catre ``marketing_knowledge_base.json``;
                implicit langa modulul ``knowledge_loader``.
        """
        self._client = llm_client
        self._swipe = load_swipe_file(swipe_path or default_swipe_path())
        self._knowledge_base = load_knowledge_base(
            knowledge_base_path or default_knowledge_base_path()
        )

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
        objective: CampaignObjective | None = None,
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
            objective: Obiectivul clientului (citit din ``ClientAccount.objective``,
                niciodata ghicit) - cand e dat, injecteaza in system prompt
                ghidajul de CTA/focus corespunzator (vezi
                :func:`build_objective_guidance`). ``None`` (implicit) = system
                prompt neschimbat, ca inainte de acest parametru.

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
            if objective is not None:
                system_prompt = f"{system_prompt}\n\n{build_objective_guidance(objective)}"
                system_prompt = (
                    f"{system_prompt}\n\n"
                    f"{build_marketing_psychology_guidance(self._knowledge_base, objective)}"
                )
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
        if objective is not None:
            system_prompt = f"{system_prompt}\n\n{build_objective_guidance(objective)}"
            system_prompt = (
                f"{system_prompt}\n\n"
                f"{build_marketing_psychology_guidance(self._knowledge_base, objective)}"
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

    def generate_omnichannel_copy(
        self, product_usp: str, niche: str, target_platform: OmniPlatform
    ) -> dict[str, Any]:
        """Genereaza copy omnicanal (Google/Meta/TikTok) din biblioteca unificata.

        Cale separata de :meth:`generate_emotional_copy`: recuperarea RAG e dupa
        nisa + platforma (nu declansator emotional), peste
        ``omnichannel_swipe_library``, cu system prompt dedicat per canal. Fara
        retry de lungime (limitele Google se aplica doar liniei istorice, nu
        acesteia) — ``generate_emotional_copy`` ramane neschimbata pentru orice
        cod existent.

        Args:
            product_usp: Propunerea unica de valoare a produsului / serviciului.
            niche: Nisa / segmentul de piata tinta (nu un cuvant cheie exact-match).
            target_platform: ``"google"``, ``"meta"`` sau ``"tiktok"``.

        Returns:
            Campurile :class:`~ppc_agent.copywriter.models.OmniAdCopy` ca dict.

        Raises:
            SwipeFileError: Daca ``omnichannel_swipe_library`` nu are nicio
                intrare pentru ``target_platform``.
            CopywriterError: Daca raspunsul clientului nu respecta schema.
        """
        examples = retrieve_omnichannel_examples(self._swipe, target_platform, niche)
        system_prompt = build_omnichannel_system_prompt(target_platform, examples)
        spec = OmniCopySpec(
            product_usp=product_usp,
            niche=" ".join(niche.split()),
            target_platform=target_platform,
            examples=examples,
            system_prompt=system_prompt,
        )
        ad = self._client.generate_omnichannel(spec)
        return ad.as_dict()

    def generate_storyboard(self, product_usp: str, target_keyword: str) -> Storyboard:
        """Genereaza si valideaza un storyboard video programatic.

        Cale noua, separata de ``generate_emotional_copy``/
        ``generate_omnichannel_copy``: LLM-ul e regizor de creatie (Lead
        Performance Creative Director), nu copywriter - iese un
        :class:`~ppc_agent.creative.video_models.Storyboard` cu scene
        cronometrate, nu text plat. Validat determinist
        (:class:`~ppc_agent.creative.video_qa.StoryboardValidator`) inainte de
        returnare - niciun storyboard care incalca regulile de productie
        (ritm/tipografie/CTA/timeline) nu ajunge la apelant.

        Args:
            product_usp: Propunerea unica de valoare a produsului / serviciului.
            target_keyword: Cuvantul cheie / nisa tinta - RAG pe
                ``tiktok_swipe_library``, acelasi mecanism ca
                ``generate_emotional_copy(platform="tiktok")``.

        Returns:
            Storyboard-ul validat.

        Raises:
            SwipeFileError: Daca ``tiktok_swipe_library`` e goala.
            CopywriterError: Raspunsul clientului nu respecta schema Storyboard.
            StoryboardValidationError: Storyboard-ul respecta schema, dar
                incalca regulile de productie video.
        """
        keyword = " ".join(target_keyword.split())
        examples = retrieve_tiktok_examples(self._swipe, keyword)
        system_prompt = build_storyboard_system_prompt(examples)
        spec = StoryboardSpec(
            product_usp=product_usp,
            target_keyword=keyword,
            examples=examples,
            system_prompt=system_prompt,
        )
        storyboard = self._client.generate_storyboard(spec)
        StoryboardValidator().validate(storyboard)
        return storyboard


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
