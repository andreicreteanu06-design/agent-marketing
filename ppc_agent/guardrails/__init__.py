"""Modulul 4 — Guardrails stricte si executie (HITL).

Se implementeaza in Faza 4:

- ``approval_gate`` — nicio scriere fara ``proposed_changes.json`` + confirmare umana
- ``spend_limiter`` — plafon absolut de cheltuiala hardcodat; exceptie la depasire
"""

from __future__ import annotations
