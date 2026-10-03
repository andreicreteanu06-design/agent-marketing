"""``ApprovalGate`` — nicio scriere fara ``proposed_changes.json`` si confirmare umana.

Fluxul obligatoriu pentru orice operatie de mutare (POST / PUT / DELETE catre
platformele de reclame):

    propose(...)  ->  flush()  ->  revizuire umana  ->  execute(confirmed=True)

``flush()`` trece intai cheltuiala totala prin :class:`AbsoluteSpendLimiter`, deci
un set care incalca limita nici macar nu se scrie pe disc. In v1, ``execute`` doar
logheaza apelurile pe care le-ar face; nu se atinge niciun API real.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ppc_agent.errors import ApprovalRequiredError
from ppc_agent.guardrails.models import ChangeSet, ExecutionReport, ProposedChange
from ppc_agent.guardrails.spend_limiter import HARD_CEILING, AbsoluteSpendLimiter

logger = logging.getLogger("ppc_agent.guardrails")

_FILENAME_PREFIX = "proposed_changes_"


class ApprovalGate:
    """Colecteaza modificari propuse, le scrie ca changeset si le executa doar confirmat."""

    def __init__(
        self,
        account: str,
        spend_limiter: AbsoluteSpendLimiter,
        *,
        output_dir: Path | str = ".",
    ) -> None:
        """Creeaza poarta de aprobare.

        Args:
            account: Identificatorul contului vizat (pentru trasabilitate).
            spend_limiter: Limitatorul absolut de cheltuiala zilnica.
            output_dir: Directorul in care se scrie ``proposed_changes_*.json``.
        """
        self._account = account
        self._limiter = spend_limiter
        self._output_dir = Path(output_dir)
        self._pending: list[ProposedChange] = []
        self._flush_seq = 0

    @property
    def pending(self) -> list[ProposedChange]:
        """Copie a modificarilor tamponate, in ordinea propunerii."""
        return list(self._pending)

    def propose(self, change: ProposedChange) -> None:
        """Adauga o modificare in tampon. Nu scrie nimic pe disc."""
        self._pending.append(change)

    def propose_many(self, changes: Iterable[ProposedChange]) -> None:
        """Adauga mai multe modificari in tampon."""
        self._pending.extend(changes)

    def build_changeset(self) -> ChangeSet:
        """Construieste :class:`ChangeSet` din modificarile tamponate (fara scriere)."""
        total = Decimal("0")
        for change in self._pending:
            total += change.spend_against_cap
        return ChangeSet(
            created_at=datetime.now(tz=UTC),
            account=self._account,
            spend_limit=self._limiter.max_daily_spend,
            hard_ceiling=HARD_CEILING,
            total_projected_daily_spend=total,
            changes=list(self._pending),
        )

    def flush(self) -> Path:
        """Valideaza limita de cheltuiala si scrie changeset-ul pe disc.

        Returns:
            Calea catre fisierul ``proposed_changes_*.json`` scris.

        Raises:
            SpendLimitExceeded: Daca totalul depaseste limita — fisierul NU se scrie.
        """
        changeset = self.build_changeset()
        self._limiter.check(changeset.total_projected_daily_spend)

        self._output_dir.mkdir(parents=True, exist_ok=True)
        stamp = changeset.created_at.strftime("%Y%m%dT%H%M%S%f")
        self._flush_seq += 1
        suffix = "" if self._flush_seq == 1 else f"_{self._flush_seq}"
        path = self._output_dir / f"{_FILENAME_PREFIX}{stamp}{suffix}.json"
        path.write_text(changeset.model_dump_json(indent=2), encoding="utf-8")
        logger.info("changeset scris: %s (%d modificari)", path, len(changeset.changes))
        return path

    @staticmethod
    def load(changeset_path: Path | str) -> ChangeSet:
        """Incarca un changeset scris anterior."""
        return ChangeSet.model_validate_json(
            Path(changeset_path).read_text(encoding="utf-8")
        )

    def execute(
        self, changeset_path: Path | str, *, confirmed: bool
    ) -> ExecutionReport:
        """Executa un changeset confirmat. In v1 doar simuleaza apelurile.

        Args:
            changeset_path: Calea catre ``proposed_changes_*.json``.
            confirmed: Trebuie sa fie exact ``True``. Orice altceva blocheaza executia.

        Returns:
            Raportul de executie cu apelurile simulate; ``applied`` este mereu ``False``.

        Raises:
            ApprovalRequiredError: Daca ``confirmed`` nu este exact ``True``.
        """
        if confirmed is not True:
            raise ApprovalRequiredError(
                "executarea necesita confirmare umana explicita (confirmed=True) "
                "dupa revizuirea proposed_changes.json"
            )
        changeset = self.load(changeset_path)
        calls = [
            f"[SIMULAT] ar apela API-ul de reclame: {change.op} {change.resource} "
            f"(sursa: {change.source_module})"
            for change in changeset.changes
        ]
        for call in calls:
            logger.info(call)
        return ExecutionReport(
            changeset_path=str(changeset_path),
            confirmed=True,
            applied=False,
            simulated_calls=calls,
        )
