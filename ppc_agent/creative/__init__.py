"""Modulul 5 — motor de generare de creatii (audio + video).

Lanteste copy-ul emotional (Modulul copywriter) intr-un anunt video ``.mp4``:

    copy -> script VO -> Fish Speech (TTS) -> .wav -> Flick (asamblare) -> .mp4

Mock-first: ``MockFishSpeechClient`` si ``MockFlickBuilder`` produc fisiere reale
pe disc (WAV silentios valid + stub MP4 + manifest), fara retea si fara ffmpeg.
Clientii ``live`` (Fish Speech local, Flick) sunt stub-uri pana la conectare.

- ``models``           — ``VoiceoverResult``, ``CreativeResult``
- ``audio_engine``     — ``BaseTtsClient`` / ``FishSpeechClient`` / ``MockFishSpeechClient``
- ``video_engine``     — ``BaseVideoBuilder`` / ``FlickVideoBuilder`` / ``MockFlickBuilder``
- ``factory``          — ``CreativeFactory`` (comuta mock/live dupa ``PPC_PROVIDER_MODE``)
- ``creative_pipeline``— ``generate_full_ad_creative(...)``
"""

from __future__ import annotations
