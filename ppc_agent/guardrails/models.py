"""Structuri de date tipizate pentru Modulul 4 (guardrails si executie HITL)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

ChangeOp = Literal["CREATE", "UPDATE", "PAUSE"]


class ProposedChange(BaseModel):
    """O singura modificare propusa unei resurse de reclame, inca neaplicata."""

    op: ChangeOp
    resource: str
    resource_type: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    projected_daily_spend: Decimal = Decimal("0")
    rationale: str
    source_module: str

    @property
    def spend_against_cap(self) -> Decimal:
        """Cat se numara la plafon: o reducere a unui buget cunoscut nu adauga cheltuiala.

        Altfel, un cont deja peste plafon n-ar putea primi nici pasii in jos - setul de
        propuneri ar fi refuzat intreg, iar cheltuiala ar ramane sus.
        """
        before = self.before.get("daily_budget")
        if before is not None and self.projected_daily_spend <= Decimal(str(before)):
            return Decimal("0")
        return self.projected_daily_spend


class ChangeSet(BaseModel):
    """Un set complet de modificari propuse pentru un cont, gata de revizuit."""

    created_at: datetime
    account: str
    spend_limit: Decimal
    hard_ceiling: Decimal
    total_projected_daily_spend: Decimal
    changes: list[ProposedChange] = Field(default_factory=list)

    def by_module(self) -> dict[str, int]:
        """Numarul de modificari pe modul sursa."""
        counts: dict[str, int] = {}
        for change in self.changes:
            counts[change.source_module] = counts.get(change.source_module, 0) + 1
        return counts


class ExecutionReport(BaseModel):
    """Rezultatul unei incercari de executie (in v1 doar simulata)."""

    changeset_path: str
    confirmed: bool
    applied: bool
    simulated_calls: list[str] = Field(default_factory=list)
