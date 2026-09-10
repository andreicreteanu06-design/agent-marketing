"""Limitator absolut de cheltuiala zilnica.

Doua nivele de protectie:

- ``HARD_CEILING`` — plafon hardcodat in cod, pe care configuratia nu il poate
  depasi. Modificarea lui necesita o schimbare de cod si o revizuire.
- ``max_daily_spend`` — limita din configuratia utilizatorului, mereu ``<=`` plafon.
"""

from __future__ import annotations

from decimal import Decimal

from ppc_agent.errors import SpendLimitExceeded

HARD_CEILING = Decimal("500.00")


class AbsoluteSpendLimiter:
    """Refuza orice set de modificari a carui cheltuiala zilnica depaseste limita."""

    def __init__(self, max_daily_spend: Decimal) -> None:
        """Configureaza limita zilnica.

        Args:
            max_daily_spend: Limita din configuratie, in moneda contului.

        Raises:
            SpendLimitExceeded: Daca limita nu este strict pozitiva sau depaseste
                :data:`HARD_CEILING`.
        """
        if max_daily_spend <= 0:
            raise SpendLimitExceeded(
                f"limita zilnica trebuie sa fie strict pozitiva, primit {max_daily_spend}"
            )
        if max_daily_spend > HARD_CEILING:
            raise SpendLimitExceeded(
                f"limita zilnica {max_daily_spend} depaseste plafonul absolut "
                f"hardcodat {HARD_CEILING}"
            )
        self._max_daily_spend = max_daily_spend

    @property
    def max_daily_spend(self) -> Decimal:
        """Limita zilnica activa."""
        return self._max_daily_spend

    @property
    def hard_ceiling(self) -> Decimal:
        """Plafonul absolut hardcodat."""
        return HARD_CEILING

    def check(self, proposed_total_daily_spend: Decimal) -> None:
        """Ridica :class:`SpendLimitExceeded` daca cheltuiala propusa depaseste limita.

        Args:
            proposed_total_daily_spend: Cheltuiala zilnica totala a setului de modificari.

        Raises:
            SpendLimitExceeded: Daca ``proposed_total_daily_spend > max_daily_spend``.
        """
        if proposed_total_daily_spend > self._max_daily_spend:
            raise SpendLimitExceeded(
                f"cheltuiala zilnica propusa {proposed_total_daily_spend} depaseste "
                f"limita {self._max_daily_spend}"
            )
