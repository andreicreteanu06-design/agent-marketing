"""Modulul 4 — Guardrails stricte si executie (HITL).

- ``models``        — ``ProposedChange``, ``ChangeSet``, ``ExecutionReport``
- ``spend_limiter`` — ``AbsoluteSpendLimiter`` + ``HARD_CEILING`` hardcodat
- ``approval_gate`` — ``ApprovalGate``: propose -> flush -> confirmare -> execute (simulat)
- ``pipeline``      — traduce iesirile Modulelor 1-3 in ``ProposedChange`` si le reda
"""

from __future__ import annotations
