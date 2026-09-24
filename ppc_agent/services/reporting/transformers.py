"""Stratul AGREGAT: din randuri brute, cifrele pe care se iau decizii.

Banii se aduna in BANI INTREGI (``int64``), nu in float. Pandas aduna float-uri cu
erori de reprezentare (0,1 + 0,2), iar un raport care arata 24,999999 lei in loc
de 25 pierde increderea clientului mai repede decat orice CPA prost. Rapoartele
(CPA, ROAS) se calculeaza abia la final, din sume exacte, cu ``Decimal``.

Trei reguli pentru ce NU se poate calcula - toate intorc ``None``, nu zero:

- **CPA fara conversii nu e zero.** Zero ar insemna "conversii gratuite",
  exact opusul adevarului.
- **ROAS fara cheltuiala nu exista**, iar la un obiectiv de lead-uri nu se
  aplica deloc: platformele nu raporteaza venit, si un ROAS de 0 ar arata ca
  un esec care nu e.
- **Evolutia fata de zero nu e +100%.** O saptamana anterioara fara cheltuieli
  nu e o baza de comparatie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

import pandas as pd

from ppc_agent.services.reporting.extractors import ReportWindow

_CENT = Decimal("0.01")
_SUM_COLUMNS = ["spend_cents", "clicks", "conversions", "revenue_cents"]

KpiKey = Literal["spend", "revenue", "conversions", "clicks", "cpa", "roas"]


def to_cents(value: object) -> int:
    """Suma in bani intregi, rotunjita ca la casa (ROUND_HALF_UP).

    Trece prin ``str`` ca un float venit din JSON (``12.34``) sa devina exact
    1234, nu 1233 din cauza reprezentarii binare.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Randurile brute in coloanele de lucru, cu banii in bani intregi."""
    return pd.DataFrame(
        {
            "date": raw["date"].map(_as_date),
            "platform": raw["platform"].astype(str),
            "spend_cents": raw["cost"].map(to_cents).astype("int64"),
            "clicks": pd.to_numeric(raw["clicks"]).fillna(0).astype("int64"),
            "conversions": pd.to_numeric(raw["conversions"]).fillna(0.0).astype(float),
            "revenue_cents": raw["revenue"].map(to_cents).astype("int64"),
        }
    )


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    """Totalurile unei perioade, cu banii exacti si rapoartele derivate din ei."""

    spend_cents: int
    clicks: int
    conversions: float
    revenue_cents: int
    track_roas: bool = True

    @property
    def spend(self) -> float:
        return self.spend_cents / 100

    @property
    def revenue(self) -> float:
        return self.revenue_cents / 100

    @property
    def cpa(self) -> float | None:
        if self.conversions <= 0:
            return None
        value = Decimal(self.spend_cents) / 100 / Decimal(str(self.conversions))
        return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))

    @property
    def roas(self) -> float | None:
        if not self.track_roas or self.spend_cents <= 0:
            return None
        value = Decimal(self.revenue_cents) / Decimal(self.spend_cents)
        return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))

    def value(self, key: KpiKey) -> float | None:
        values: dict[KpiKey, float | None] = {
            "spend": self.spend,
            "revenue": self.revenue if self.track_roas else None,
            "conversions": round(self.conversions, 2),
            "clicks": float(self.clicks),
            "cpa": self.cpa,
            "roas": self.roas,
        }
        return values[key]


def in_window(frame: pd.DataFrame, window: ReportWindow) -> pd.DataFrame:
    """Doar randurile din ``window``."""
    if frame.empty:
        return frame
    mask = (frame["date"] >= window.start) & (frame["date"] <= window.end)
    return frame.loc[mask]


def totals(frame: pd.DataFrame, window: ReportWindow, *, track_roas: bool = True) -> PeriodTotals:
    """Totalurile ferestrei ``window``."""
    scoped = in_window(frame, window)
    return PeriodTotals(
        spend_cents=int(scoped["spend_cents"].sum()),
        clicks=int(scoped["clicks"].sum()),
        conversions=float(scoped["conversions"].sum()),
        revenue_cents=int(scoped["revenue_cents"].sum()),
        track_roas=track_roas,
    )


def daily_series(
    frame: pd.DataFrame, window: ReportWindow, *, track_roas: bool = True
) -> list[tuple[date, PeriodTotals]]:
    """Cate un punct pe FIECARE zi din fereastra, in ordine.

    Platformele omit zilele fara livrare; aici ele devin zile cu zero, ca
    graficul sa nu sara peste ele si sa lege doua puncte departate intre ele.
    """
    scoped = in_window(frame, window)
    grouped = scoped.groupby("date")[_SUM_COLUMNS].sum()
    daily = grouped.reindex(pd.Index(window.dates(), name="date"), fill_value=0)
    return [
        (
            day,
            PeriodTotals(
                spend_cents=int(row["spend_cents"]),
                clicks=int(row["clicks"]),
                conversions=float(row["conversions"]),
                revenue_cents=int(row["revenue_cents"]),
                track_roas=track_roas,
            ),
        )
        for day, row in daily.iterrows()
        if isinstance(day, date)
    ]


def platform_totals(
    frame: pd.DataFrame,
    window: ReportWindow,
    platforms: list[str],
    *,
    track_roas: bool = True,
) -> list[tuple[str, PeriodTotals]]:
    """Totalurile ferestrei pe fiecare platforma care a raspuns - si cele cu zero."""
    scoped = in_window(frame, window)
    sums = scoped.groupby("platform")[_SUM_COLUMNS].sum().to_dict(orient="index")
    result: list[tuple[str, PeriodTotals]] = []
    for platform in platforms:
        row = sums.get(platform)
        if row is None:
            result.append((platform, PeriodTotals(0, 0, 0.0, 0, track_roas=track_roas)))
            continue
        result.append(
            (
                platform,
                PeriodTotals(
                    spend_cents=int(row["spend_cents"]),
                    clicks=int(row["clicks"]),
                    conversions=float(row["conversions"]),
                    revenue_cents=int(row["revenue_cents"]),
                    track_roas=track_roas,
                ),
            )
        )
    return result


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Evolutia procentuala, cu o zecimala - ``None`` cand nu are sens."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


@dataclass(frozen=True, slots=True)
class KpiChange:
    key: KpiKey
    current: float | None
    previous: float | None
    change_pct: float | None


KPI_ORDER: tuple[KpiKey, ...] = ("spend", "conversions", "cpa", "roas", "revenue", "clicks")


def week_over_week(current: PeriodTotals, previous: PeriodTotals) -> list[KpiChange]:
    """Fiecare indicator, cu valoarea curenta, cea anterioara si evolutia."""
    changes: list[KpiChange] = []
    for key in KPI_ORDER:
        now, before = current.value(key), previous.value(key)
        changes.append(
            KpiChange(key=key, current=now, previous=before, change_pct=pct_change(now, before))
        )
    return changes
