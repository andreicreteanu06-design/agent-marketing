"""Servicii de aplicatie: logica ce coordoneaza mai multe parti ale domeniului.

Distinct de ``providers/`` (vorbesc cu platforme externe), ``decision/``
(matematica) si ``guardrails/`` (reguli de siguranta): aici stau pasii care le
imbina, fara sa stie nimic despre HTTP sau despre schema bazei de date.
"""

from __future__ import annotations
