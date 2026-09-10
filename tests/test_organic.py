"""Teste pentru fuziunea datelor organice: filtru afisari, scor intentie, semnale GBP."""

from __future__ import annotations

import pandas as pd
import pytest

from ppc_agent.ingestion.organic import intent_score, to_local_signals, to_seed_keywords


def _gsc_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("impressions", "kept"),
    [(99, False), (100, False), (101, True), (500, True)],
)
def test_impression_filter_boundary(impressions: int, kept: bool) -> None:
    frame = _gsc_frame(
        [
            {
                "query": "program facturare",
                "clicks": 5,
                "impressions": impressions,
                "ctr": 0.05,
                "position": 4.0,
            }
        ]
    )
    seeds = to_seed_keywords(frame, min_impressions=100)
    assert bool(seeds) is kept


def test_seed_keywords_sorted_by_intent_desc() -> None:
    frame = _gsc_frame(
        [
            {"query": "curs facturare gratuit", "clicks": 2, "impressions": 900,
             "ctr": 0.02, "position": 9.0},
            {"query": "pret program facturare", "clicks": 40, "impressions": 900,
             "ctr": 0.12, "position": 2.0},
        ]
    )
    seeds = to_seed_keywords(frame)
    assert [seed.query for seed in seeds] == [
        "pret program facturare",
        "curs facturare gratuit",
    ]
    assert seeds[0].intent_score > seeds[1].intent_score


def test_intent_score_rewards_commercial_and_position() -> None:
    commercial = intent_score("pret servicii contabilitate", position=1.0, ctr=0.1)
    informational = intent_score("ce este contabilitatea", position=10.0, ctr=0.01)
    assert commercial > 0.8
    assert informational < 0.3
    assert 0.0 <= informational <= 1.0


def test_to_local_signals_parses_reviews() -> None:
    raw: dict[str, object] = {
        "name": "ContApp SRL",
        "categories": ["Software company"],
        "review_count": 87,
        "avg_rating": 4.6,
        "reviews": [
            {"text": "Excelent, recomand", "score": 1.0, "label": "pozitiv"},
            {"text": "Suport lent si scump", "score": -1.0, "label": "negativ"},
        ],
    }
    signals = to_local_signals(raw)
    assert signals.name == "ContApp SRL"
    assert signals.review_count == 87
    assert signals.avg_rating == pytest.approx(4.6)
    assert signals.sentiment_mix == {"pozitiv": 1, "neutru": 0, "negativ": 1}


def test_to_local_signals_tolerates_missing_fields() -> None:
    signals = to_local_signals({"name": "X"})
    assert signals.review_count == 0
    assert signals.reviews == []
