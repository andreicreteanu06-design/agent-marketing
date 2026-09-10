"""Expansiunea cuvintelor cheie: DataFrame Keyword Planner -> modele tipizate."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from ppc_agent.ingestion.models import ExpandedKeyword, MatchType


def _to_match_type(value: str) -> MatchType:
    if value == "exact":
        return "exact"
    if value == "phrase":
        return "phrase"
    return "broad"


def expand_keywords(frame: pd.DataFrame) -> list[ExpandedKeyword]:
    """Converteste DataFrame-ul Keyword Planner in :class:`ExpandedKeyword` tipizate.

    Args:
        frame: DataFrame cu coloanele ``keyword``, ``avg_monthly_searches``,
            ``competition``, ``low_top_bid``, ``high_top_bid``,
            ``match_type_suggestion``.

    Returns:
        Lista sortata descrescator dupa ``avg_monthly_searches``.
    """
    out: list[ExpandedKeyword] = []
    for record in frame.to_dict(orient="records"):
        out.append(
            ExpandedKeyword(
                keyword=str(record["keyword"]),
                avg_monthly_searches=int(record["avg_monthly_searches"]),
                competition=round(float(record["competition"]), 4),
                low_top_bid=Decimal(str(record["low_top_bid"])),
                high_top_bid=Decimal(str(record["high_top_bid"])),
                match_type_suggestion=_to_match_type(str(record["match_type_suggestion"])),
            )
        )
    out.sort(key=lambda keyword: keyword.avg_monthly_searches, reverse=True)
    return out
