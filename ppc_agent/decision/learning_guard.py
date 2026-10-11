"""Garda fazei de invatare Meta: nu reseta invatarea cu o schimbare care poate astepta.

O modificare majora a unui ad set (buget schimbat mult, reclame noi, alta targetare,
alt eveniment) reporneste faza de invatare de la zero. Resetarile repetate costa mai
mult decat "Learning Limited", deci cat timp ad set-ul invata:

- **schimbarile mici de buget** (pana la :data:`MAX_BUDGET_CHANGE`) trec;
- **orice altceva** se amana, iar propunerea ramane in asteptare.

Garda nu blocheaza la infinit:

- **Learning Limited cu CPA la tinta**: invatarea e incheiata practic, daca nu si
  tehnic - schimbarile trec;
- **7 zile in invatare** (``LEARNING_WINDOW_DAYS``) fara iesire: interdictia cade, ca
  strategia sa poata pivota.

Functie pura: aceeasi stare da acelasi verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from ppc_agent.alignment.meta_liquidity import LEARNING_WINDOW_DAYS

#: O schimbare de buget pana la atat (relativ) nu e considerata majora.
MAX_BUDGET_CHANGE = Decimal("0.20")
#: ``learning_stage_info.status``: Meta raporteaza Learning Limited ca ``FAIL``.
_LEARNING = "LEARNING"
_LIMITED = frozenset({"FAIL", "LEARNING_LIMITED"})

Change = Literal["budget", "major"]


@dataclass(frozen=True, slots=True)
class LearningState:
    """Starea de invatare a unui ad set, citita din Meta."""

    status: str
    #: Ultima modificare semnificativa (de cand invata); ``None`` = necunoscut.
    since: datetime | None = None
    #: Cheltuiala si conversiile din ultimele 7 zile, pentru CPA.
    spend: Decimal = Decimal("0")
    conversions: float = 0.0

    @property
    def cpa(self) -> Decimal | None:
        if self.conversions <= 0:
            return None
        return self.spend / Decimal(str(self.conversions))


def learning_hold(
    state: LearningState | None,
    *,
    change: Change,
    budget_change: Decimal | None = None,
    target_cpa: Decimal | None = None,
    now: datetime,
) -> str | None:
    """De ce se amana schimbarea, sau ``None`` cand poate pleca.

    Args:
        state: Starea ad set-ului; ``None`` = necunoscuta (nu blocheaza).
        change: ``budget`` sau ``major`` (reclame noi, targetare, eveniment).
        budget_change: Schimbarea relativa de buget (0.15 = 15%); ``None`` = necunoscuta,
            tratata ca majora.
        target_cpa: CPA-ul tinta al contului, pentru Learning Limited.
        now: Momentul verificarii (cu fus orar).
    """
    if state is None or (state.status != _LEARNING and state.status not in _LIMITED):
        return None
    cpa = state.cpa
    if (
        state.status in _LIMITED
        and target_cpa is not None
        and target_cpa > 0
        and cpa is not None
        and cpa <= target_cpa
    ):
        return None  # incheiata practic: CPA-ul e la tinta
    if state.since is not None and now - state.since >= timedelta(days=LEARNING_WINDOW_DAYS):
        return None  # o saptamana fara iesire: lasam strategia sa pivoteze
    if change == "budget" and budget_change is not None and budget_change <= MAX_BUDGET_CHANGE:
        return None
    phase = "invata" if state.status == _LEARNING else "e in Learning Limited, cu CPA peste tinta"
    what = (
        f"o schimbare de buget de {budget_change:.0%}"
        if change == "budget" and budget_change is not None
        else "o modificare majora"
    )
    return (
        f"ad set-ul {phase}: {what} ar reporni invatarea de la zero. Se amana pana iese din "
        f"invatare sau trec {LEARNING_WINDOW_DAYS:.0f} zile; schimbarile de buget de pana la "
        f"{MAX_BUDGET_CHANGE:.0%} trec oricand."
    )
