"""Teste pentru utilitarele de text: normalizare, potrivire de fraze, sentiment."""

from __future__ import annotations

import pytest

from ppc_agent.texttools import contains_phrase, normalize, score_sentiment, tokenize


def test_normalize_strips_diacritics_and_case() -> None:
    assert normalize("Facturare RAPIDĂ și Ieftină") == "facturare rapida si ieftina"


def test_tokenize_splits_on_punctuation() -> None:
    assert tokenize("pret, ofertă! (2024)") == ["pret", "oferta", "2024"]


def test_contains_phrase_matches_contiguous_tokens_only() -> None:
    assert contains_phrase("cel mai bun program de facturare", "program de facturare")
    assert not contains_phrase("program bun de facturare", "program de facturare")


def test_contains_phrase_is_diacritic_insensitive() -> None:
    assert contains_phrase("Contabilitate Ieftină", "ieftina")


@pytest.mark.parametrize(
    ("text", "expected_label"),
    [
        ("Serviciu excelent, recomand, suport amabil si rapid.", "pozitiv"),
        ("Groaznic, aplicatia e lenta si suportul nepoliticos.", "negativ"),
        ("Am folosit aplicatia marti dimineata.", "neutru"),
        ("", "neutru"),
    ],
)
def test_score_sentiment_labels(text: str, expected_label: str) -> None:
    score, label = score_sentiment(text)
    assert label == expected_label
    if expected_label == "pozitiv":
        assert score > 0
    elif expected_label == "negativ":
        assert score < 0
    else:
        assert score == pytest.approx(0.0)
