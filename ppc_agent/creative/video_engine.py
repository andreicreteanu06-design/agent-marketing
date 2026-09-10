"""Integrare Flick / Creatorberry (asamblare video) pentru anuntul final ``.mp4``.

``FlickVideoBuilder`` combina un b-roll de fundal, vocea Fish Speech si subtitrari
dinamice intr-un ``.mp4``. ``MockFlickBuilder`` scrie un stub MP4 valid ca structura
(box ``ftyp``) plus un manifest ``.json`` cu intrarile folosite — testabil offline,
fara ffmpeg.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from ppc_agent.errors import SetupRequiredError, VideoAssemblyError

# Box ``ftyp`` minim valid: size(4) + 'ftyp'(4) + major(4) + minor(4) + brands(8) = 24.
_MP4_FTYP_STUB = bytes.fromhex(
    "00000018"  # box size = 24
    "66747970"  # 'ftyp'
    "69736f6d"  # major brand 'isom'
    "00000200"  # minor version
    "69736f6d69736f32"  # compatible brands 'isom', 'iso2'
)


class BaseVideoBuilder(ABC):
    """Interfata unui asamblor video: b-roll + voce + subtitrari -> ``.mp4``."""

    engine: str = "base"

    @abstractmethod
    def build(
        self,
        *,
        broll_path: Path,
        voiceover_path: Path,
        subtitle_text: str,
        out_path: Path,
    ) -> Path:
        """Asambleaza anuntul video.

        Args:
            broll_path: Video de fundal (b-roll / product shot).
            voiceover_path: Fisierul ``.wav`` cu naratiunea.
            subtitle_text: Textul exact al anuntului, pentru subtitrari dinamice.
            out_path: Calea ``.mp4`` de scris.

        Returns:
            Calea fisierului ``.mp4`` scris.

        Raises:
            VideoAssemblyError: Daca o intrare lipseste de pe disc sau asamblarea esueaza.
        """


def manifest_path(mp4_path: Path) -> Path:
    """Calea manifestului JSON alaturat unui ``.mp4`` (``<mp4>.manifest.json``)."""
    return mp4_path.with_name(f"{mp4_path.name}.manifest.json")


def _require_inputs(broll_path: Path, voiceover_path: Path, subtitle_text: str) -> None:
    if not broll_path.is_file():
        raise VideoAssemblyError(f"b-roll-ul nu exista: {broll_path}")
    if not voiceover_path.is_file():
        raise VideoAssemblyError(f"voice-over-ul nu exista: {voiceover_path}")
    if not subtitle_text.strip():
        raise VideoAssemblyError("textul pentru subtitrari este gol")


class MockFlickBuilder(BaseVideoBuilder):
    """Flick simulat: stub MP4 + manifest ``<mp4>.manifest.json`` cu intrarile."""

    engine = "mock-flick"

    def build(
        self,
        *,
        broll_path: Path,
        voiceover_path: Path,
        subtitle_text: str,
        out_path: Path,
    ) -> Path:
        """Scrie un stub ``.mp4`` si un manifest JSON alaturat."""
        _require_inputs(broll_path, voiceover_path, subtitle_text)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        out_path.write_bytes(_MP4_FTYP_STUB)
        manifest = {
            "engine": self.engine,
            "broll": str(broll_path),
            "voiceover": str(voiceover_path),
            "subtitles": subtitle_text,
        }
        manifest_path(out_path).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return out_path


class FlickVideoBuilder(BaseVideoBuilder):
    """Asamblor Flick / Creatorberry real. Stub pana la conectare."""

    engine = "flick"

    def __init__(self, endpoint: str = "", api_key: str = "") -> None:
        self._endpoint = endpoint
        self._api_key = api_key

    def build(
        self,
        *,
        broll_path: Path,
        voiceover_path: Path,
        subtitle_text: str,
        out_path: Path,
    ) -> Path:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        _require_inputs(broll_path, voiceover_path, subtitle_text)
        raise SetupRequiredError(
            "Flick live neimplementat. Seteaza PPC_FLICK_ENDPOINT si PPC_FLICK_API_KEY "
            f"(endpoint curent: '{self._endpoint or 'neconfigurat'}'). "
            "Pana atunci ruleaza cu MockFlickBuilder."
        )
