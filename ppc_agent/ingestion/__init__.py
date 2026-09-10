"""Modulul 1 — Motor de context si ingestie.

Se implementeaza in Faza 1:

- ``crawler``  — extrage ``PageContext`` dintr-un URL (Playwright, fallback httpx + BS4)
- ``organic``  — fuziune date GSC (interogari organice) + semnale locale GBP
- ``keywords`` — expansiune prin Keyword Planner
- ``negatives`` — schela deterministica de cuvinte cheie negative, inainte de lansare
"""

from __future__ import annotations
