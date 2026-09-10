"""Modulul 2 — Motor matematic de decizie.

Se implementeaza in Faza 2:

- ``budget``      — alocare de buget prin Thompson Sampling (bandit bayesian, posteriori Beta)
- ``attribution`` — atribuire prin lanturi Markov, cu efect de eliminare (removal effect)

Fara logica bazata pe reguli. Fiecare formula are o nota "Math:" in docstring si
un test cu un caz verificabil manual.
"""

from __future__ import annotations
