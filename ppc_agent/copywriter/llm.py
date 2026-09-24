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

from ppc_agent.copywriter.models import (
    AdCopy,
    CopySpec,
    OmniAdCopy,
    OmniCopySpec,
    ReportSummary,
    ReportSummarySpec,
    StoryboardSpec,
    TikTokAdCopy,
    TikTokCopySpec,
    char_count,
)
from ppc_agent.creative.video_models import (
    AudioTrack,
    Scene,
    Storyboard,
    TextOverlay,
    VideoCanvas,
)
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

    def generate_tiktok(self, spec: TikTokCopySpec) -> TikTokAdCopy:
        """Genereaza un script TikTok conform ``spec``.

        Metoda concreta (nu abstracta), cu implicit ``NotImplementedError`` —
        clientii de test existenti (care implementeaza doar :meth:`generate`)
        raman instantiabili fara modificari. Clientii reali (:class:`MockLLMClient`,
        :class:`LiveLLMClient`) o suprascriu.
        """
        raise NotImplementedError(
            f"{type(self).__name__} nu suporta generarea de copy TikTok"
        )

    def generate_omnichannel(self, spec: OmniCopySpec) -> OmniAdCopy:
        """Genereaza copy omnicanal (Google/Meta/TikTok) conform ``spec``.

        Metoda concreta (nu abstracta), acelasi motiv ca la
        :meth:`generate_tiktok`: clientii de test existenti raman instantiabili
        fara modificari; clientii reali o suprascriu.
        """
        raise NotImplementedError(
            f"{type(self).__name__} nu suporta generarea de copy omnicanal"
        )

    def generate_storyboard(self, spec: StoryboardSpec) -> Storyboard:
        """Genereaza un storyboard video programatic conform ``spec``.

        Metoda concreta (nu abstracta), acelasi motiv ca la
        :meth:`generate_tiktok`/:meth:`generate_omnichannel`: clientii de test
        existenti raman instantiabili fara modificari; clientii reali o
        suprascriu. Rezultatul NU e validat aici (vezi
        :class:`~ppc_agent.creative.video_qa.StoryboardValidator`, aplicat de
        apelant - :meth:`~ppc_agent.copywriter.engine.AdCopyGenerator.generate_storyboard`).
        """
        raise NotImplementedError(
            f"{type(self).__name__} nu suporta generarea de storyboard"
        )

    def generate_report_summary(self, spec: ReportSummarySpec) -> ReportSummary:
        """Scrie rezumatul executiv al unui raport saptamanal din ``spec.facts``.

        Metoda concreta, acelasi motiv ca la celelalte: clientii de test existenti
        raman instantiabili. Rezultatul NU e verificat aici - cifrele lui se
        confrunta cu faptele in ``services/reporting/summary.py``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} nu suporta rezumatul de raport"
        )


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

# Banci pentru randarea determinista a scripturilor TikTok, pe unghi creativ.
# Nu copiaza textul exemplelor recuperate din swipe library (acelea sunt doar
# context) — compune propriu, ca si generatorul Google de mai sus.
_TIKTOK_ANGLES: tuple[str, ...] = (
    "contrarian_warning",
    "problem_solution",
    "ugc_unboxing",
    "objection_first",
    "mistake_opener",
)

_TIKTOK_HOOKS: dict[str, str] = {
    "contrarian_warning": "Nu mai face asta cu {kw} pana nu vezi clipul asta",
    "problem_solution": "Daca ai probleme cu {kw}, uite ce am gasit",
    "ugc_unboxing": "Am comandat {kw} si va arat exact ce am primit",
    "objection_first": "Stiu ce gandesti despre {kw} - hai sa lamurim",
    "mistake_opener": "Greseala pe care o fac toti cu {kw}",
}

_TIKTOK_VISUAL: dict[str, str] = {
    "contrarian_warning": "Zoom rapid pe defect, camera usor instabila",
    "problem_solution": "Split-screen inainte / dupa",
    "ugc_unboxing": "Prim-plan pe ambalaj, mana care despacheteaza",
    "objection_first": "Vorbeste direct in camera, fara filtru",
    "mistake_opener": "Gest de stop cu mana, apoi produsul in cadru",
}


_CAPTION_MIN = 24
_CAPTION_MAX = 32
_CAPTION_FILLER = " - vezi acum cum functioneaza exact"


def _fit_caption(text: str) -> str:
    """Ajusteaza ``text`` sa incapa strict in fereastra 24-32 caractere.

    Text sursa (hook/USP recuperat din swipe library) poate avea orice
    lungime - taie la granita de cuvant daca depaseste maximul, completeaza cu
    un filler fix daca nu atinge minimul. Garanteaza regula de tipografie a
    lui StoryboardValidator indiferent de continutul sursa (inclusiv gol).
    """
    cleaned = " ".join(text.split()).strip(" -,.;")
    while len(cleaned) < _CAPTION_MIN:
        cleaned = (cleaned + _CAPTION_FILLER).strip()
    if len(cleaned) > _CAPTION_MAX:
        words = cleaned.split(" ")
        out = ""
        for word in words:
            candidate = word if not out else f"{out} {word}"
            if len(candidate) > _CAPTION_MAX:
                break
            out = candidate
        cleaned = out if len(out) >= _CAPTION_MIN else cleaned[:_CAPTION_MAX]
    return cleaned


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

    def generate_tiktok(self, spec: TikTokCopySpec) -> TikTokAdCopy:
        """Randeaza :class:`TikTokAdCopy` determinist: hook + body + cta.

        Foloseste primul exemplu recuperat (daca exista) doar ca ancora usoara
        pentru CTA si dovada — nu copiaza text 1:1, la fel ca partea Google.
        """
        keyword = " ".join(spec.target_keyword.split())
        usp = " ".join(spec.product_usp.split()).rstrip(".")
        angle = _TIKTOK_ANGLES[_stable_index(f"{keyword}|tiktok", len(_TIKTOK_ANGLES))]
        example = spec.examples[0] if spec.examples else None

        cta = example.cta_text if example else "Link in bio"
        body = f"{usp}." if usp else f"Solutie pentru {keyword}."
        if example is not None:
            body = f"{body} {example.mechanism_proof}"

        return TikTokAdCopy(
            visual_hook_concept=_TIKTOK_VISUAL[angle],
            audio_hook=_TIKTOK_HOOKS[angle].format(kw=keyword),
            body_script=body,
            text_overlay=[_titlecase_keyword(keyword), "Dovedit", cta],
            call_to_action=cta,
            creative_angle=angle,
        )

    def generate_omnichannel(self, spec: OmniCopySpec) -> OmniAdCopy:
        """Randeaza :class:`OmniAdCopy` determinist din ``spec``.

        Foloseste cel mai relevant exemplu recuperat (daca exista) ca ancora
        pentru hook/problema/dovada/cta — nu copiaza text 1:1, la fel ca partea
        Google si TikTok de mai sus.
        """
        niche = " ".join(spec.niche.split())
        usp = " ".join(spec.product_usp.split()).rstrip(".")
        example = spec.examples[0] if spec.examples else None

        proof = f"{usp}." if usp else f"Solutie dovedita pentru {niche}."
        if example is not None:
            proof = f"{proof} {example.mechanism_proof}"

        return OmniAdCopy(
            hook_type=example.hook_type if example else "direct_offer",
            hook_text=example.hook_text if example else f"Ai nevoie de {niche}?",
            problem_agitation=(
                example.problem_agitation
                if example
                else f"Problema cu {niche} nu se rezolva singura."
            ),
            mechanism_proof=proof,
            offer_cta=example.offer_cta if example else "Afla mai multe",
        )

    def generate_storyboard(self, spec: StoryboardSpec) -> Storyboard:
        """Randeaza un :class:`Storyboard` de 3 scene (hook/proof/cta), 22s.

        Determinist si construit sa respecte StoryboardValidator prin design:
        caption-ul din scena de dovada trece prin :func:`_fit_caption`
        (headline-urile si CTA nu au limita de caractere), iar CTA-ul intra in
        fereastra finala (start=17s, durata=5s, pe un total de 22s).
        """
        keyword = " ".join(spec.target_keyword.split())
        example = spec.examples[0] if spec.examples else None

        hook_text = example.hook_audio if example else f"Atentie la {keyword or 'asta'}"
        proof_caption = _fit_caption(
            example.mechanism_proof if example else "Rezultatul se vede din prima zi"
        )
        cta_text = example.cta_text if example else "Afla mai multe din link"
        hook_broll = (
            example.hook_visual if example else "Zoom rapid, intrerupere de tipar"
        )

        return Storyboard(
            job_id="mock_storyboard",
            duration_seconds=22.0,
            canvas=VideoCanvas(),
            scenes=[
                Scene(
                    id="scene_1_hook",
                    start_time=0.0,
                    end_time=2.5,
                    purpose="hook",
                    visual_broll_prompt=hook_broll,
                    text_layers=[
                        TextOverlay(
                            type="headline",
                            text=hook_text,
                            start_time=0.2,
                            duration=2.0,
                            anchor_position="safe_center",
                            highlight_words=[keyword] if keyword else [],
                            contrast_mode="adaptive_backplate",
                        )
                    ],
                    audio=[
                        AudioTrack(
                            type="voiceover", asset_ref="mock_hook.wav", start_time=0.0
                        )
                    ],
                ),
                Scene(
                    id="scene_2_proof",
                    start_time=2.5,
                    end_time=16.0,
                    purpose="proof",
                    visual_broll_prompt="Split-screen inainte / dupa, prim-plan pe detaliu",
                    text_layers=[
                        TextOverlay(
                            type="caption",
                            text=proof_caption,
                            start_time=4.0,
                            duration=1.5,
                            anchor_position="bottom_center",
                            contrast_mode="adaptive_backplate",
                        )
                    ],
                    audio=[
                        AudioTrack(
                            type="voiceover", asset_ref="mock_proof.wav", start_time=2.5
                        )
                    ],
                ),
                Scene(
                    id="scene_3_cta",
                    start_time=16.0,
                    end_time=22.0,
                    purpose="cta",
                    visual_broll_prompt="Produsul in cadru static, logo vizibil",
                    text_layers=[
                        TextOverlay(
                            type="cta",
                            text=cta_text,
                            start_time=17.0,
                            duration=5.0,
                            anchor_position="safe_center",
                            contrast_mode="adaptive_backplate",
                        )
                    ],
                    audio=[
                        AudioTrack(
                            type="voiceover", asset_ref="mock_cta.wav", start_time=16.0
                        )
                    ],
                ),
            ],
        )

    def generate_report_summary(self, spec: ReportSummarySpec) -> ReportSummary:
        """Intoarce rezumatul determinist din ``spec`` - fara model, fara inventie."""
        return ReportSummary(summary=spec.template)


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


def _build_tiktok_user_prompt(spec: TikTokCopySpec) -> str:
    """User prompt-ul TikTok, cu exemplele dovedite recuperate ca ancora RAG."""
    lines = [
        f"Nisa / cuvant cheie tinta: {spec.target_keyword}",
        f"USP produs/serviciu: {spec.product_usp}",
        f"Declansator emotional: {spec.emotion_trigger}",
    ]
    for example in spec.examples:
        lines.append(
            f"Exemplu dovedit ({example.niche}, activ {example.days_active_proxy} zile): "
            f'hook audio "{example.hook_audio}" | dovada "{example.mechanism_proof}" | '
            f'cta "{example.cta_text}"'
        )
    lines.append(
        'Raspunde DOAR cu JSON: {"visual_hook_concept": "...", "audio_hook": "...", '
        '"body_script": "...", "text_overlay": ["...", "..."], "call_to_action": "...", '
        '"creative_angle": "..."}'
    )
    return "\n".join(lines)


def _build_omni_user_prompt(spec: OmniCopySpec) -> str:
    """User prompt-ul omnicanal, cu exemplele dovedite (filtrate pe platforma) ca ancora RAG."""
    lines = [
        f"Nisa / segment tinta: {spec.niche}",
        f"Platforma tinta: {spec.target_platform}",
        f"USP produs/serviciu: {spec.product_usp}",
    ]
    for example in spec.examples:
        lines.append(
            f"Exemplu dovedit ({example.niche}, {example.performance_signal}): "
            f'hook "{example.hook_text}" | problema "{example.problem_agitation}" | '
            f'dovada "{example.mechanism_proof}" | cta "{example.offer_cta}"'
        )
    lines.append(
        'Raspunde DOAR cu JSON: {"hook_type": "...", "hook_text": "...", '
        '"problem_agitation": "...", "mechanism_proof": "...", "offer_cta": "..."}'
    )
    return "\n".join(lines)


def _build_storyboard_user_prompt(spec: StoryboardSpec) -> str:
    """User prompt-ul pentru storyboard, cu exemplele dovedite ca ancora RAG."""
    lines = [
        f"Cuvant cheie / nisa: {spec.target_keyword}",
        f"USP produs/serviciu: {spec.product_usp}",
    ]
    for example in spec.examples:
        lines.append(
            f"Exemplu dovedit ({example.niche}, activ {example.days_active_proxy} zile): "
            f'hook "{example.hook_audio}" | dovada "{example.mechanism_proof}" | '
            f'cta "{example.cta_text}"'
        )
    lines.append(
        "Raspunde DOAR cu JSON valid conform schemei Storyboard din system prompt "
        "(job_id, duration_seconds, canvas, scenes)."
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

    def _call_ollama_chat(self, system_prompt: str, user_prompt: str) -> Any:
        """Trimite system+user prompt catre Ollama; returneaza continutul JSON parsat.

        Centralizeaza conectare/timeout/model lipsa/raspuns intrerupt — reutilizat
        de :meth:`generate` si :meth:`generate_tiktok`, ca ``PPC_LLM_NUM_GPU`` si
        toate mesajele de eroare sa ramana valabile peste tot, fara duplicare.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar cu eroare HTTP sau raspuns intrerupt.
        """
        options: dict[str, Any] = {"temperature": 0.6}
        if self._num_gpu is not None:
            options["num_gpu"] = self._num_gpu
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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

        data = response.json()
        if data.get("done") is False:
            raise CopywriterError(
                f"Ollama a intrerupt generarea pentru '{self._model}' inainte de a "
                "termina raspunsul (posibil model corupt sau incarcare esuata). "
                "Verifica 'ollama ps' si log-urile serverului, sau redescarca-l: "
                f"ollama pull {self._model}"
            )
        content = data["message"]["content"]
        return json.loads(content)

    def generate(self, spec: CopySpec) -> AdCopy:
        """Cere modelului Ollama copy conform ``spec``; parseaza JSON-ul returnat.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar continutul nu e JSON valid cu
                campurile asteptate.
        """
        try:
            parsed = self._call_ollama_chat(spec.system_prompt, _build_user_prompt(spec))
            return AdCopy.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid cu campurile "
                f"asteptate (headline_1/headline_2/description): {exc}"
            ) from exc

    def generate_tiktok(self, spec: TikTokCopySpec) -> TikTokAdCopy:
        """Cere modelului Ollama un script TikTok conform ``spec``.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar continutul nu e JSON valid cu
                schema :class:`TikTokAdCopy`.
        """
        try:
            parsed = self._call_ollama_chat(
                spec.system_prompt, _build_tiktok_user_prompt(spec)
            )
            return TikTokAdCopy.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid pentru "
                f"schema TikTokAdCopy: {exc}"
            ) from exc

    def generate_omnichannel(self, spec: OmniCopySpec) -> OmniAdCopy:
        """Cere modelului Ollama copy omnicanal (Google/Meta/TikTok) conform ``spec``.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar continutul nu e JSON valid cu
                schema :class:`OmniAdCopy`.
        """
        try:
            parsed = self._call_ollama_chat(
                spec.system_prompt, _build_omni_user_prompt(spec)
            )
            return OmniAdCopy.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid pentru "
                f"schema OmniAdCopy: {exc}"
            ) from exc

    def generate_storyboard(self, spec: StoryboardSpec) -> Storyboard:
        """Cere modelului Ollama un storyboard video conform ``spec``.

        Nu valideaza fata de regulile de productie (StoryboardValidator) -
        doar fata de schema. Apelantul (AdCopyGenerator.generate_storyboard)
        aplica validarea determinista dupa aceasta parsare.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: Serverul a raspuns, dar continutul nu e JSON valid pentru
                schema Storyboard.
        """
        try:
            parsed = self._call_ollama_chat(
                spec.system_prompt, _build_storyboard_user_prompt(spec)
            )
            return Storyboard.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid pentru "
                f"schema Storyboard: {exc}"
            ) from exc

    def generate_report_summary(self, spec: ReportSummarySpec) -> ReportSummary:
        """Cere modelului Ollama rezumatul executiv al unui raport.

        Raises:
            SetupRequiredError: Ollama nu raspunde, timeout, sau modelul nu e descarcat.
            CopywriterError: raspunsul nu e JSON valid cu campul ``summary``.
        """
        user_prompt = "Fapte:\n" + "\n".join(f"- {fact}" for fact in spec.facts)
        try:
            parsed = self._call_ollama_chat(spec.system_prompt, user_prompt)
            return ReportSummary.model_validate(parsed)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise CopywriterError(
                f"raspunsul modelului '{self._model}' nu e JSON valid cu campul "
                f"'summary': {exc}"
            ) from exc
