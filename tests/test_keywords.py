"""Teste pentru expansiunea de cuvinte cheie si furnizorul mock Keyword Planner."""

from __future__ import annotations

from decimal import Decimal

from ppc_agent.ingestion.keywords import expand_keywords
from ppc_agent.providers.mock.google import MockKeywordPlannerProvider


def test_mock_expansion_is_deterministic() -> None:
    provider = MockKeywordPlannerProvider()
    first = provider.expand(["program facturare"], "RO", "ro")
    second = provider.expand(["program facturare"], "RO", "ro")
    assert first.equals(second)


def test_mock_expansion_covers_each_seed() -> None:
    provider = MockKeywordPlannerProvider()
    frame = provider.expand(["facturare", "contabilitate"], "RO", "ro")
    keywords = set(frame["keyword"])
    assert "facturare" in keywords
    assert "pret contabilitate" in keywords


def test_expand_keywords_types_and_sort() -> None:
    provider = MockKeywordPlannerProvider()
    frame = provider.expand(["program facturare", "e-factura"], "RO", "ro")
    expanded = expand_keywords(frame)

    assert len(expanded) == len(frame)
    volumes = [kw.avg_monthly_searches for kw in expanded]
    assert volumes == sorted(volumes, reverse=True)

    sample = expanded[0]
    assert isinstance(sample.low_top_bid, Decimal)
    assert sample.match_type_suggestion in ("broad", "phrase", "exact")
    assert sample.high_top_bid >= sample.low_top_bid
