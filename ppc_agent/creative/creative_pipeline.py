"""Orchestratorul Modulului 5: copy emotional -> voce -> video ``.mp4``."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from rich.console import Console

from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.llm import BaseLLMClient
from ppc_agent.copywriter.models import AdCopy, TikTokAdCopy
from ppc_agent.copywriter.swipe import load_swipe_file, retrieve_framework
from ppc_agent.creative.audio_engine import BaseTtsClient, estimate_duration_seconds
from ppc_agent.creative.models import CreativeResult, VoiceoverResult
from ppc_agent.creative.video_engine import BaseVideoBuilder
from ppc_agent.errors import VideoAssemblyError

_OUTPUT_DIR = "creative_output"
_DEFAULT_TRIGGER = "aida"
Platform = Literal["google", "tiktok"]


def _join_sentences(parts: tuple[str, ...]) -> str:
    sentences = [
        part.rstrip() if part.rstrip().endswith((".", "!", "?")) else f"{part.rstrip()}."
        for part in parts
        if part.strip()
    ]
    return " ".join(sentences)


def build_vo_script(ad: AdCopy) -> str:
    """Compune scriptul de voice-over din copy-ul anuntului, cu punctuatie curata."""
    return _join_sentences((ad.headline_1, ad.headline_2, ad.description))


def build_tiktok_vo_script(ad: TikTokAdCopy) -> str:
    """Compune scriptul de voce TikTok din hook + body + cta, cu punctuatie curata."""
    return _join_sentences((ad.audio_hook, ad.body_script, ad.call_to_action))


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:40] or "creative"


def synthesize_voiceover(
    tts: BaseTtsClient, script: str, wav_path: Path
) -> VoiceoverResult:
    """Ruleaza clientul TTS si impacheteaza rezultatul."""
    written = tts.synthesize(script, wav_path)
    return VoiceoverResult(
        script=script,
        wav_path=str(written),
        duration_seconds=estimate_duration_seconds(script),
        voice=tts.voice,
        engine=tts.engine,
    )


def generate_full_ad_creative(
    llm_client: BaseLLMClient,
    tts: BaseTtsClient,
    video: BaseVideoBuilder,
    *,
    keyword: str,
    raw_broll_path: Path | str,
    emotion_trigger: str = _DEFAULT_TRIGGER,
    product_usp: str | None = None,
    platform: Platform = "google",
    output_dir: Path | str = _OUTPUT_DIR,
    swipe_path: Path | str | None = None,
) -> CreativeResult:
    """Ruleaza intregul lant: copywriter -> Fish Speech -> Flick -> ``.mp4``.

    Toti cei trei clienti sunt injectati (fara instantiere directa in interior),
    ca sa poata fi comutati intre ``mock`` si ``live`` de catre apelant.

    Args:
        llm_client: Clientul de generare de copy (mock sau live).
        tts: Clientul text-to-speech (mock sau live).
        video: Asamblorul video (mock sau live).
        keyword: Cuvantul cheie exact-match (google) / nisa tinta (tiktok).
        raw_broll_path: Video de fundal (b-roll / product shot) — trebuie sa existe.
        emotion_trigger: Declansatorul emotional pentru copywriter.
        product_usp: Propunerea unica de valoare; daca lipseste, se deriva din keyword.
        platform: ``"google"`` (implicit, 16:9) sau ``"tiktok"`` (script UGC, 9:16).
        output_dir: Directorul in care se scriu ``.wav`` si ``.mp4``.
        swipe_path: Cale ``swipe_file.json`` (pentru RAG-ul de copywriting).

    Returns:
        :class:`CreativeResult` cu toate caile si manifestul.

    Raises:
        CopywriterError / SwipeFileError: din pasul de copywriting.
        TtsError: din sinteza vocala.
        VideoAssemblyError: din asamblarea video.
    """
    broll = Path(raw_broll_path)
    if not broll.is_file():
        raise VideoAssemblyError(f"b-roll-ul nu exista: {broll}")

    usp = product_usp or f"Solutie pentru {keyword}, rapid si fara batai de cap"
    generator = AdCopyGenerator(llm_client, swipe_path=swipe_path)
    out_dir = Path(output_dir)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")

    if platform == "tiktok":
        copy_dict = generator.generate_emotional_copy(
            usp, keyword, emotion_trigger, platform="tiktok"
        )
        tiktok_ad = TikTokAdCopy.model_validate(copy_dict)
        script = build_tiktok_vo_script(tiktok_ad)

        base = f"{_slug(keyword)}_tiktok_{stamp}"
        wav_path = out_dir / f"{base}.wav"
        mp4_path = out_dir / f"{base}.mp4"
        voiceover = synthesize_voiceover(tts, script, wav_path)
        written_mp4 = video.build(
            broll_path=broll,
            voiceover_path=Path(voiceover.wav_path),
            subtitle_text=script,
            out_path=mp4_path,
            visual_hook_concept=tiktok_ad.visual_hook_concept,
            text_overlay=tiktok_ad.text_overlay,
            aspect_ratio="9:16",
        )
        return CreativeResult(
            created_at=datetime.now(tz=UTC),
            platform="tiktok",
            keyword=keyword,
            emotion_trigger=emotion_trigger,
            creative_angle=tiktok_ad.creative_angle,
            product_usp=usp,
            ad_copy=tiktok_ad,
            script=script,
            subtitle_text=script,
            broll_path=str(broll),
            voiceover_path=voiceover.wav_path,
            mp4_path=str(written_mp4),
            duration_seconds=voiceover.duration_seconds,
            manifest={
                "llm_client": type(llm_client).__name__,
                "tts_engine": voiceover.engine,
                "video_engine": video.engine,
                "creative_angle": tiktok_ad.creative_angle,
            },
        )

    copy_dict = generator.generate_emotional_copy(usp, keyword, emotion_trigger)
    ad = AdCopy.model_validate(copy_dict)

    framework = retrieve_framework(load_swipe_file(swipe_path), emotion_trigger)
    script = build_vo_script(ad)

    base = f"{_slug(keyword)}_{framework.style}_{stamp}"
    wav_path = out_dir / f"{base}.wav"
    mp4_path = out_dir / f"{base}.mp4"

    voiceover = synthesize_voiceover(tts, script, wav_path)
    written_mp4 = video.build(
        broll_path=broll,
        voiceover_path=Path(voiceover.wav_path),
        subtitle_text=script,
        out_path=mp4_path,
    )

    return CreativeResult(
        created_at=datetime.now(tz=UTC),
        platform="google",
        keyword=keyword,
        emotion_trigger=emotion_trigger,
        framework_style=framework.style,
        product_usp=usp,
        ad_copy=ad,
        script=script,
        subtitle_text=script,
        broll_path=str(broll),
        voiceover_path=voiceover.wav_path,
        mp4_path=str(written_mp4),
        duration_seconds=voiceover.duration_seconds,
        manifest={
            "llm_client": type(llm_client).__name__,
            "tts_engine": voiceover.engine,
            "video_engine": video.engine,
            "framework": framework.name,
        },
    )


def render_creative(result: CreativeResult, console: Console) -> None:
    """Afiseaza rezumatul creatiei generate in consola."""
    label = result.creative_angle if result.platform == "tiktok" else result.framework_style
    console.print(
        f"\n[bold]Creatie video generata[/bold]  platforma={result.platform}  "
        f"keyword='{result.keyword}'  trigger='{result.emotion_trigger}'  stil={label}"
    )
    console.print(f"  script VO : {result.script}")
    console.print(f"  b-roll    : {result.broll_path}")
    console.print(
        f"  voce      : {result.voiceover_path}  (~{result.duration_seconds:.1f}s, "
        f"{result.manifest.get('tts_engine', 'n/a')})"
    )
    console.print(
        f"  video     : [green]{result.mp4_path}[/green]  "
        f"({result.manifest.get('video_engine', 'n/a')})"
    )
