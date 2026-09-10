"""Modulul 1 — Motor de context si ingestie.

- ``crawler``   — extrage ``PageContext`` dintr-un URL (Playwright, fallback httpx + BS4)
- ``organic``   — fuziune date GSC (interogari organice) + semnale locale GBP
- ``keywords``  — expansiune prin Keyword Planner
- ``negatives`` — schela deterministica de cuvinte cheie negative, inainte de lansare
- ``pipeline``  — orchestrarea + redarea in consola
"""

from __future__ import annotations
