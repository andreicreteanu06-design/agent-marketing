"""Cererea reala a Researcher-ului: Google Trends prin ``pytrends``, fara retea.

``pytrends`` e inlocuit cu un ``TrendReq`` fals (acelasi API: ``build_payload``,
``interest_over_time`` -> DataFrame cu coloana cuvantului si ``isPartial``), deci
adaptorul real ruleaza cap-coada. Restul (seria cererii, cache-ul, notele) e pur.
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from typing import Any, ClassVar

import pandas as pd
import pytest

from ppc_agent_server.services.market_trends import (
    FAILURE_TTL_SECONDS,
    TIMEFRAME,
    GoogleTrends,
    TrendPoint,
    TrendsUnavailableError,
    demand_from_trends,
    load_trend_demand,
)
from ppc_agent_server.services.market_trends import (
    pytrends_interest as real_pytrends_interest,  # conftest inlocuieste numele din modul
)
from ppc_agent_server.services.researcher import market_trend


class _FakeTrendReq:
    """``pytrends.request.TrendReq`` fals: tine minte cererile, intoarce ``frame``."""

    calls: ClassVar[list[tuple[str, Any]]] = []
    frame: pd.DataFrame = pd.DataFrame()
    error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(("init", kwargs))

    def build_payload(self, kw_list: list[str], *, timeframe: str, geo: str) -> None:
        self.calls.append(("payload", (kw_list, timeframe, geo)))

    def interest_over_time(self) -> pd.DataFrame:
        if self.error is not None:
            raise self.error
        return self.frame


@pytest.fixture
def fake_pytrends(monkeypatch: pytest.MonkeyPatch) -> type[_FakeTrendReq]:
    _FakeTrendReq.calls = []
    _FakeTrendReq.error = None
    module = types.ModuleType("pytrends.request")
    module.TrendReq = _FakeTrendReq  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytrends.request", module)
    return _FakeTrendReq


def _frame(keyword: str, values: list[int], *, partial_last: bool) -> pd.DataFrame:
    index = pd.date_range(end="2026-09-20", periods=len(values), freq="7D", name="date")
    partial = [False] * len(values)
    partial[-1] = partial_last
    return pd.DataFrame({keyword: values, "isPartial": partial}, index=index)


def test_the_adapter_asks_five_years_in_the_client_country_and_drops_the_partial_week(
    fake_pytrends: type[_FakeTrendReq],
) -> None:
    fake_pytrends.frame = _frame("service auto", [40, 45, 50, 3], partial_last=True)

    points = real_pytrends_interest("service auto", "RO")

    assert points == [
        TrendPoint(date(2026, 8, 30), 40),
        TrendPoint(date(2026, 9, 6), 45),
        TrendPoint(date(2026, 9, 13), 50),
    ]
    init, payload = fake_pytrends.calls
    assert init[1]["hl"] == "ro-RO"
    # Fara retries/backoff: pytrends 4.9 + urllib3 2 ar pica la constructie.
    assert not {"retries", "backoff_factor"} & set(init[1])
    assert payload[1] == (["service auto"], TIMEFRAME, "RO")


def test_an_empty_answer_is_an_empty_series(fake_pytrends: type[_FakeTrendReq]) -> None:
    fake_pytrends.frame = pd.DataFrame()

    assert real_pytrends_interest("nisa rara", "RO") == []


def test_a_refusal_from_google_becomes_trends_unavailable(
    fake_pytrends: type[_FakeTrendReq],
) -> None:
    class TooManyRequestsError(Exception):
        pass

    fake_pytrends.error = TooManyRequestsError("429")

    with pytest.raises(TrendsUnavailableError, match=r"n-a răspuns \(TooManyRequestsError\)"):
        real_pytrends_interest("service auto", "RO")


def test_without_pytrends_installed_the_demand_is_simply_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pytrends.request", None)

    with pytest.raises(TrendsUnavailableError, match="pytrends nu e instalat"):
        real_pytrends_interest("service auto", "RO")


# --- seria cererii -------------------------------------------------------------------------


def _five_years(value_for: Any) -> list[TrendPoint]:
    first = date(2021, 9, 26)
    return [
        TrendPoint(first + timedelta(weeks=week), value_for(first + timedelta(weeks=week)))
        for week in range(260)
    ]


def test_five_years_of_weeks_give_the_trend_last_year_and_the_season() -> None:
    # Octombrie dublu fata de restul anului; ultimele 4 saptamani urca.
    points = _five_years(lambda day: 80 if day.month == 10 else 40)
    points[-4:] = [TrendPoint(point.week, 60) for point in points[-4:]]

    demand = demand_from_trends("service auto", points)

    assert demand is not None
    assert (demand.unit, demand.source) == ("index", "Google Trends")
    assert demand.category == "service auto"
    assert len(demand.weekly) == 260 and demand.weekly[-4:] == [60, 60, 60, 60]
    assert demand.same_weeks_last_year == sum(p.value for p in points[-56:-52])
    assert len(demand.monthly_index) == 12
    assert demand.monthly_index[9] > 1.5 > demand.monthly_index[0]
    assert round(sum(demand.monthly_index) / 12, 2) == 1.0
    trend = market_trend(demand, today=date(2026, 9, 25))
    assert (trend.direction, trend.season) == ("growing", "rising")


@pytest.mark.parametrize(
    "points",
    [
        [],
        [TrendPoint(date(2026, 1, 4) + timedelta(weeks=week), 50) for week in range(5)],
        [TrendPoint(date(2026, 1, 4) + timedelta(weeks=week), 0) for week in range(20)],
    ],
    ids=["gol", "prea-scurt", "doar-zero"],
)
def test_too_little_interest_gives_no_demand(points: list[TrendPoint]) -> None:
    assert demand_from_trends("nisa rara", points) is None


def test_under_two_years_the_season_stays_unknown() -> None:
    points = [
        TrendPoint(date(2025, 10, 5) + timedelta(weeks=week), 50) for week in range(52)
    ]

    demand = demand_from_trends("service auto", points)

    assert demand is not None and demand.monthly_index == ()
    assert demand.same_weeks_last_year is None
    assert market_trend(demand, today=date(2026, 9, 25)).season == "unknown"


# --- cache-ul si pauza ------------------------------------------------------------------------


def test_one_request_per_niche_and_country_per_day() -> None:
    calls: list[tuple[str, str]] = []
    today = [date(2026, 9, 25)]

    def fetch(keyword: str, geo: str) -> list[TrendPoint]:
        calls.append((keyword, geo))
        return [TrendPoint(date(2026, 9, 20), 50)]

    trends = GoogleTrends(fetch=fetch, today=lambda: today[0])

    for _ in range(3):
        trends.weekly_interest("Service Auto ", geo="ro")
    trends.weekly_interest("service auto", geo="MD")
    today[0] += timedelta(days=1)
    trends.weekly_interest("service auto", geo="RO")

    assert calls == [("Service Auto", "RO"), ("service auto", "MD"), ("service auto", "RO")]


def test_a_refusal_is_remembered_so_google_is_not_hammered() -> None:
    calls: list[str] = []
    now = [1000.0]
    refuse = [True]

    def fetch(keyword: str, geo: str) -> list[TrendPoint]:
        calls.append(keyword)
        if refuse[0]:
            raise TrendsUnavailableError("Google Trends n-a răspuns (TooManyRequestsError)")
        return []

    trends = GoogleTrends(fetch=fetch, clock=lambda: now[0])

    for _ in range(3):
        with pytest.raises(TrendsUnavailableError, match="TooManyRequestsError"):
            trends.weekly_interest("service auto", geo="RO")
    assert len(calls) == 1

    refuse[0] = False
    now[0] += FAILURE_TTL_SECONDS + 1
    assert trends.weekly_interest("service auto", geo="RO") == []
    assert len(calls) == 2


class _Source:
    def __init__(self, points: list[TrendPoint] | None = None, error: Exception | None = None):
        self.points = points or []
        self.error = error

    def weekly_interest(self, keyword: str, *, geo: str) -> list[TrendPoint]:
        if self.error is not None:
            raise self.error
        return self.points


def test_the_loader_never_raises_and_says_what_is_missing() -> None:
    refused = load_trend_demand(
        _Source(error=TrendsUnavailableError("limită")), "service auto", geo="RO", country="România"
    )
    broken = load_trend_demand(
        _Source(error=KeyError("default")), "service auto", geo="RO", country="România"
    )
    quiet = load_trend_demand(_Source(), "service auto", geo="RO", country="România")
    found = load_trend_demand(
        _Source(_five_years(lambda day: 50)), "service auto", geo="RO", country="România"
    )

    assert refused == (
        None,
        "Google Trends nu a răspuns acum pentru «service auto» (limită): trendul cererii rămâne "
        "necunoscut.",
    )
    assert broken == (None, "Trendul cererii nu s-a putut citi (KeyError).")
    assert quiet[0] is None and "nu are destul interes" in quiet[1] and "România" in quiet[1]
    assert found[0] is not None and found[1] == ""
