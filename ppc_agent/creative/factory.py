"""``CreativeFactory`` — comuta intre clientii ``mock`` si ``live`` pentru creatii.

Aceeasi abordare ca :class:`~ppc_agent.providers.factory.ProviderFactory`: alegerea
se face dupa ``PPC_PROVIDER_MODE`` din configuratie.
"""

from __future__ import annotations

from ppc_agent.config import AppConfig, ProviderMode
from ppc_agent.creative.audio_engine import (
    BaseTtsClient,
    FishSpeechClient,
    MockFishSpeechClient,
)
from ppc_agent.creative.video_engine import (
    BaseVideoBuilder,
    FlickVideoBuilder,
    MockFlickBuilder,
)


class CreativeFactory:
    """Construieste clientii de sinteza vocala si de asamblare video."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def mode(self) -> ProviderMode:
        """Modul activ (``mock`` sau ``live``)."""
        return self._config.provider_mode

    def tts(self) -> BaseTtsClient:
        """Clientul text-to-speech pentru modul activ."""
        settings = self._config.settings
        if self.mode is ProviderMode.LIVE:
            return FishSpeechClient(
                endpoint=settings.fish_speech_url, voice=settings.fish_speech_voice
            )
        return MockFishSpeechClient(voice=settings.fish_speech_voice)

    def video(self) -> BaseVideoBuilder:
        """Asamblorul video pentru modul activ."""
        settings = self._config.settings
        if self.mode is ProviderMode.LIVE:
            return FlickVideoBuilder(
                endpoint=settings.flick_endpoint, api_key=settings.flick_api_key
            )
        return MockFlickBuilder()
