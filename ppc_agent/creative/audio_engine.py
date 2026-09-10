"""Integrare Fish Speech (text-to-speech) pentru vocea din anunturile video.

``FishSpeechClient`` trimite scriptul VO catre o instanta locala Fish Speech si
primeste un ``.wav``. ``MockFishSpeechClient`` produce un WAV silentios valid pe
disc, cu o durata estimata din lungimea scriptului — testabil offline.
"""

from __future__ import annotations

import wave
from abc import ABC, abstractmethod
from pathlib import Path

from ppc_agent.errors import SetupRequiredError, TtsError

_WORDS_PER_SECOND = 2.4  # ~145 cuvinte/minut, ritm de voice-over
_MIN_DURATION = 1.0
_SAMPLE_RATE = 22_050


def estimate_duration_seconds(script: str) -> float:
    """Durata estimata a naratiunii, din numarul de cuvinte."""
    words = len(script.split())
    return round(max(_MIN_DURATION, words / _WORDS_PER_SECOND), 2)


class BaseTtsClient(ABC):
    """Interfata unui client text-to-speech: script -> fisier ``.wav``."""

    engine: str = "base"

    @property
    def voice(self) -> str:
        """Identificatorul vocii folosite (implicit ``n/a``)."""
        return "n/a"

    @abstractmethod
    def synthesize(self, script: str, out_path: Path) -> Path:
        """Sintetizeaza ``script`` intr-un fisier WAV la ``out_path``.

        Args:
            script: Textul de rostit.
            out_path: Calea fisierului ``.wav`` de scris.

        Returns:
            Calea fisierului scris.

        Raises:
            TtsError: Daca scriptul e gol sau sinteza esueaza.
        """


class MockFishSpeechClient(BaseTtsClient):
    """Fish Speech simulat: scrie un WAV silentios valid, cu durata plauzibila."""

    engine = "mock-fish-speech"

    def __init__(self, voice: str = "ro_default") -> None:
        self._voice = voice

    @property
    def voice(self) -> str:
        """Vocea configurata."""
        return self._voice

    def synthesize(self, script: str, out_path: Path) -> Path:
        """Scrie un WAV mono, 16-bit, silentios, lung cat naratiunea estimata."""
        text = script.strip()
        if not text:
            raise TtsError("scriptul pentru voice-over este gol")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        duration = estimate_duration_seconds(text)
        n_frames = int(duration * _SAMPLE_RATE)
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_SAMPLE_RATE)
            wav.writeframes(b"\x00\x00" * n_frames)
        return out_path


class FishSpeechClient(BaseTtsClient):
    """Client Fish Speech real (instanta locala). Stub pana la conectare."""

    engine = "fish-speech"

    def __init__(self, endpoint: str = "", voice: str = "ro_default") -> None:
        self._endpoint = endpoint
        self._voice = voice

    @property
    def voice(self) -> str:
        """Vocea configurata."""
        return self._voice

    def synthesize(self, script: str, out_path: Path) -> Path:
        """Nu este disponibil in v1 — vezi :class:`SetupRequiredError`."""
        raise SetupRequiredError(
            "Fish Speech live neimplementat. Porneste o instanta locala si seteaza "
            f"PPC_FISH_SPEECH_URL (endpoint curent: '{self._endpoint or 'neconfigurat'}'). "
            "Pana atunci ruleaza cu MockFishSpeechClient."
        )
