"""Modul de copywriting direct-response, cu incarcatura emotionala.

Genereaza copy pentru Google Ads pornind de la un fisier local de formule
(``swipe_file.json``, abordare RAG locala), fortand cuvantul cheie exact intr-un
headline si respectand limitele Google Ads. Rezultatele merg intr-o coada locala
(``proposed_ads_queue.json``) pentru aprobare umana - nimic nu se publica online.

- ``models``   — ``Framework``, ``SwipeFile``, ``AdCopy``, ``CopySpec``, ``QueuedAd``
- ``swipe``    — incarcarea si recuperarea framework-ului dupa declansatorul emotional
- ``llm``      — ``BaseLLMClient`` (interfata), ``MockLLMClient`` (determinist), stub ``live``
- ``engine``   — ``AdCopyGenerator`` + ``check_google_limits``
- ``pipeline`` — orchestrarea CLI + scrierea in coada
"""

from __future__ import annotations
