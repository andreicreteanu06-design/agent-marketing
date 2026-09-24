"""Ce au in comun citirile zi-cu-zi ale furnizorilor live.

Un singur loc pentru fereastra de date si pentru coloane, ca Google Ads si Meta
sa intoarca exact aceeasi forma - raportul saptamanal le pune una langa alta.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ppc_agent.errors import ProviderError

#: Coloanele unei citiri zilnice: cele din ``campaign_performance()``, plus ``date``.
DAILY_COLUMNS = ["date", "arm_id", "name", "clicks", "conversions", "cost", "revenue"]


def daily_window(days: int, end_date: date | None) -> tuple[date, date]:
    """Intervalul ``[start, end]`` (ambele incluse) pentru o citire zilnica.

    ``end_date`` implicit e IERI, in UTC: ziua de azi nu s-a incheiat, iar
    platformele mai ajusteaza cifrele ultimelor ore.

    Raises:
        ProviderError: ``days`` nu e pozitiv.
    """
    if days <= 0:
        raise ProviderError(f"numarul de zile trebuie sa fie pozitiv ({days})")
    end = end_date or (datetime.now(tz=UTC).date() - timedelta(days=1))
    return end - timedelta(days=days - 1), end
