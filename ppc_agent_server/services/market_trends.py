"""Cererea reala pentru Researcher (CSO): interesul de cautare din Google Trends.

Inlocuieste seria demonstrativa a cererii: pentru nisa clientului (``market_focus``,
din cautarile lui reale) se cere interesul saptamanal din ultimii 5 ani, in tara
lui, prin ``pytrends`` (clientul neoficial, fara cheie, al Google Trends). Din el
iese :class:`~ppc_agent_server.services.researcher.DemandSeries`:

- **saptamanile** - indicele 0-100 al Google (100 = saptamana cu cel mai mare
  interes din fereastra), nu numar de cautari; ``unit="index"`` spune asta mai
  departe, in textele Researcher-ului;
- **aceleasi 4 saptamani de anul trecut** - din aceeasi serie (indicele e
  comparabil in interiorul ferestrei);
- **sezonul** - media fiecarei luni pe toti anii, raportata la media anului.

Google Trends limiteaza repede cererile automate (429). De aceea: o singura cerere
per nisa si tara pe zi (cache pe proces), iar un esec se tine minte
:data:`FAILURE_TTL_SECONDS`, ca un 429 sa nu fie repetat la fiecare intrebare din
chat. Un esec nu opreste nimic: cererea ramane necunoscuta, cu o nota.

Singura cerere reala e :func:`pytrends_interest`; testele o inlocuiesc.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Protocol

from ppc_agent_server.services.researcher import TREND_WEEKS, DemandSeries

logger = logging.getLogger("ppc_agent_server.services.market_trends")

#: Fereastra ceruta: 5 ani, saptamanal - destul pentru sezon si pentru anul trecut.
TIMEFRAME = "today 5-y"
#: Cat asteapta o cerere catre Google Trends (conectare, citire).
TRENDS_TIMEOUT_SECONDS = (5.0, 15.0)
#: Un esec (429, retea) se tine minte atat, ca sa nu fie repetat la fiecare intrebare.
FAILURE_TTL_SECONDS = 15 * 60.0
#: Saptamanile dintr-un an: "aceleasi saptamani de anul trecut".
WEEKS_PER_YEAR = 52
#: Ca sezonul sa insemne ceva, fiecare luna trebuie sa apara in cel putin atatia ani.
MIN_YEARS_FOR_SEASON = 2


class TrendsUnavailableError(RuntimeError):
    """Google Trends n-a dat o serie (limita, retea, pachet lipsa, raspuns neasteptat)."""


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """O saptamana din Google Trends: ziua cu care incepe si indicele 0-100."""

    week: date
    value: int


class TrendsSource(Protocol):
    """Interesul saptamanal pentru un cuvant, intr-o tara (cele mai vechi primele)."""

    def weekly_interest(self, keyword: str, *, geo: str) -> list[TrendPoint]: ...


def pytrends_interest(keyword: str, geo: str, timeframe: str = TIMEFRAME) -> list[TrendPoint]:
    """Singura cerere reala: ``pytrends`` -> saptamanile complete (fara cea in curs).

    Raises:
        TrendsUnavailableError: pachetul lipseste, Google a refuzat (429) sau raspunsul
            nu are forma asteptata.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:
        raise TrendsUnavailableError(
            "pachetul pytrends nu e instalat (pip install -r requirements-server.txt)"
        ) from exc
    try:
        # Fara retries/backoff: pytrends 4.9 construieste atunci un Retry cu un argument
        # scos din urllib3 2 (method_whitelist). Reincercarea e oricum a noastra: a doua zi.
        client = TrendReq(hl="ro-RO", tz=-120, timeout=TRENDS_TIMEOUT_SECONDS)
        client.build_payload([keyword], timeframe=timeframe, geo=geo)
        frame = client.interest_over_time()
    except Exception as exc:  # pytrends arunca requests/pandas/ResponseError, fara ierarhie
        raise TrendsUnavailableError(f"Google Trends n-a răspuns ({type(exc).__name__})") from exc
    if frame.empty or keyword not in frame.columns:
        return []
    partial = frame["isPartial"] if "isPartial" in frame.columns else None
    points: list[TrendPoint] = []
    for index, value in frame[keyword].items():
        if partial is not None and bool(partial.loc[index]):
            continue  # saptamana in curs: incompleta, ar arata o scadere falsa
        points.append(TrendPoint(week=index.date(), value=int(value)))
    return points


class GoogleTrends:
    """:class:`TrendsSource` prin Google Trends, cu cache pe zi si pauza dupa un esec."""

    def __init__(
        self,
        *,
        fetch: Callable[[str, str], list[TrendPoint]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._today = today
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, date], list[TrendPoint]] = {}
        self._failed: dict[tuple[str, str], tuple[float, str]] = {}

    def weekly_interest(self, keyword: str, *, geo: str) -> list[TrendPoint]:
        key = (keyword.strip().lower(), geo.upper())
        day = self._today()
        with self._lock:
            cached = self._series.get((*key, day))
            if cached is not None:
                return cached
            failure = self._failed.get(key)
            if failure is not None and self._clock() < failure[0]:
                raise TrendsUnavailableError(failure[1])
        # Cererea in afara lock-ului: doua nise diferite nu se asteapta una pe alta.
        fetch = self._fetch or pytrends_interest
        try:
            points = fetch(keyword.strip(), geo.upper())
        except TrendsUnavailableError as exc:
            with self._lock:
                self._failed[key] = (self._clock() + FAILURE_TTL_SECONDS, str(exc))
            raise
        with self._lock:
            # Doar ziua de azi ramane: cheile vechi nu se mai cer niciodata.
            self._series = {k: v for k, v in self._series.items() if k[2] == day}
            self._series[(*key, day)] = points
            self._failed.pop(key, None)
        return points

    def clear(self) -> None:
        """Uita seriile si esecurile - pentru teste."""
        with self._lock:
            self._series.clear()
            self._failed.clear()


#: Sursa implicita a procesului (cache-ul e al ei).
google_trends = GoogleTrends()


def _monthly_index(points: Sequence[TrendPoint]) -> tuple[float, ...]:
    """Media fiecarei luni (pe toti anii), raportata la media lunilor; gol = nu se poate."""
    by_month: defaultdict[int, list[int]] = defaultdict(list)
    years: defaultdict[int, set[int]] = defaultdict(set)
    for point in points:
        by_month[point.week.month].append(point.value)
        years[point.week.month].add(point.week.year)
    if len(by_month) < 12 or min(len(seen) for seen in years.values()) < MIN_YEARS_FOR_SEASON:
        return ()
    means = [fmean(by_month[month]) for month in range(1, 13)]
    average = fmean(means)
    if average <= 0:
        return ()
    return tuple(round(mean / average, 4) for mean in means)


def demand_from_trends(keyword: str, points: Sequence[TrendPoint]) -> DemandSeries | None:
    """Seria cererii din saptamanile Google Trends; ``None`` = prea putin sau doar zero."""
    ordered = sorted(points, key=lambda point: point.week)
    if len(ordered) < TREND_WEEKS or not any(point.value for point in ordered[-TREND_WEEKS:]):
        return None
    weekly = [point.value for point in ordered]
    last_year = (
        sum(weekly[-WEEKS_PER_YEAR - 4 : -WEEKS_PER_YEAR])
        if len(weekly) >= WEEKS_PER_YEAR + 4
        else None
    )
    return DemandSeries(
        category=keyword,
        weekly=weekly,
        same_weeks_last_year=last_year or None,
        monthly_index=_monthly_index(ordered),
        unit="index",
        source="Google Trends",
    )


def load_trend_demand(
    source: TrendsSource, keyword: str, *, geo: str, country: str
) -> tuple[DemandSeries | None, str]:
    """Cererea pentru nisa, sau ``(None, nota)`` - nu arunca niciodata."""
    try:
        points = source.weekly_interest(keyword, geo=geo)
    except TrendsUnavailableError as exc:
        logger.warning("[Researcher] Google Trends pentru «%s» (%s): %s", keyword, geo, exc)
        return None, (
            f"Google Trends nu a răspuns acum pentru «{keyword}» ({exc}): trendul cererii "
            "rămâne necunoscut."
        )
    except Exception as exc:  # o sursa noua nu are voie sa opreasca Researcher-ul
        logger.exception("[Researcher] sursa de trend a picat pentru «%s»", keyword)
        return None, f"Trendul cererii nu s-a putut citi ({type(exc).__name__})."
    demand = demand_from_trends(keyword, points)
    if demand is None:
        return None, (
            f"Google Trends nu are destul interes de căutare pentru «{keyword}» în {country}: "
            "trendul cererii rămâne necunoscut."
        )
    return demand, ""
