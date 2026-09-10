"""Orchestratorul Modulului 5: copy emotional -> voce -> video ``.mp4``."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.llm import MockLLMClient
from ppc_agent.copywriter.models import AdCopy
from ppc_agent.copywriter.swipe import load_swipe_file, retrieve_framework
from ppc_agent.creative.audio_engine import BaseTtsClient, estimate_duration_seconds
from ppc_agent.creative.models import CreativeResult, VoiceoverResult
from ppc_agent.creative.video_engine import BaseVideoBuilder
from ppc_agent.errors import VideoAssemblyError

_OUTPUT_DIR = "creative_output"
_DEFAULT_TRIGGER = "aida"


def build_vo_script(ad: AdCopy) -> str:
    """Compune scriptul de voice-over din copy-ul anuntului, cu punctuatie curata."""
    parts = (ad.headline_1, ad.headline_2, ad.description)
    sentences = [
        part.rstrip() if part.rstrip().endswith((".", "!", "?")) else f"{part.rstrip()}."
        for part in parts
        if part.strip()
    ]
    return " ".join(sentences)


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
    tts: BaseTtsClient,
    video: BaseVideoBuilder,
    *,
    keyword: str,
    raw_broll_path: Path | str,
    emotion_trigger: str = _DEFAULT_TRIGGER,
    product_usp: str | None = None,
    output_dir: Path | str = _OUTPUT_DIR,
    swipe_path: Path | str | None = None,
) -> CreativeResult:
    """Ruleaza intregul lant: copywriter -> Fish Speech -> Flick -> ``.mp4``.

    Args:
        tts: Clientul text-to-speech (mock sau live).
        video: Asamblorul video (mock sau live).
        keyword: Cuvantul cheie exact-match al anuntului.
        raw_broll_path: Video de fundal (b-roll / product shot) — trebuie sa existe.
        emotion_trigger: Declansatorul emotional pentru copywriter.
        product_usp: Propunerea unica de valoare; daca lipseste, se deriva din keyword.
        output_dir: Directorul in care se scriu ``.wav`` si ``.mp4``.
        swipe_path: Cale ``swipe_file.json`` (pentru numele/stilul framework-ului).

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
    generator = AdCopyGenerator(MockLLMClient(), swipe_path=swipe_path)
    copy_dict = generator.generate_emotional_copy(usp, keyword, emotion_trigger)
    ad = AdCopy.model_validate(copy_dict)

    framework = retrieve_framework(load_swipe_file(swipe_path), emotion_trigger)
    script = build_vo_script(ad)

    out_dir = Path(output_dir)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
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
            "tts_engine": voiceover.engine,
            "video_engine": video.engine,
            "framework": framework.name,
        },
    )


def render_creative(result: CreativeResult, console: Console) -> None:
    """Afiseaza rezumatul creatiei generate in consola."""
    console.print(
        f"\n[bold]Creatie video generata[/bold]  keyword='{result.keyword}'  "
        f"trigger='{result.emotion_trigger}'  framework={result.framework_style}"
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
