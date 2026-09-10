"""Agent PPC — planificare si management de campanii Google Ads si Meta Ads.

Pachetul expune o interfata CLI (``python -m ppc_agent.cli``) si module separate:

- ``providers``  — adaptoare catre sisteme externe (implementari ``mock`` sau ``live``)
- ``ingestion``  — Modulul 1: crawling domeniu, fuziune date organice, expansiune cuvinte cheie
- ``decision``   — Modulul 2: alocare buget (Thompson Sampling) + atribuire (lanturi Markov)
- ``alignment``  — Modulul 3: optimizare Quality Score + lichiditate algoritmica Meta
- ``guardrails`` — Modulul 4: poarta de aprobare (HITL) + limitator absolut de cheltuiala

In versiunea 1 nu se fac apeluri reale catre platformele de reclame: modul implicit
al furnizorilor este ``mock``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
