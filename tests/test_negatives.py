"""Teste pentru schela de cuvinte cheie negative (deterministica, fara ML)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ppc_agent.ingestion.models import ExpandedKeyword, PageContext
from ppc_agent.ingestion.negatives import (
    DEFAULT_INTENT_THRESHOLD,
    commercial_intent,
    scaffold_negatives,
)


def _kw(keyword: str) -> ExpandedKeyword:
    return ExpandedKeyword(
        keyword=keyword,
        avg_monthly_searches=1000,
        competition=0.5,
        low_top_bid=Decimal("1.00"),
        high_top_bid=Decimal("2.00"),
        match_type_suggestion="broad",
    )


def _page() -> PageContext:
    return PageContext(
        url="https://contapp.ro",
        ok=True,
        status_code=200,
        title="ContApp",
        h1=["Contabilitate online pentru firme"],
        h2=["Preturi simple"],
    )


@pytest.mark.parametrize(
    ("keyword", "expected_reason"),
    [
        ("ce este contabilitatea", "TOKEN_INFORMATIONAL"),
        ("program facturare gratis", "TOKEN_PRICE_SHOPPER"),
        ("joburi contabilitate", "TOKEN_JOB_SEEKER"),
        ("factura in excel", "TOKEN_DIY"),
    ],
)
def test_each_token_rule(keyword: str, expected_reason: str) -> None:
    result = scaffold_negatives([_kw(keyword)], _page(), competitor_brands=[])
    assert result.items[0].reason_code == expected_reason
    assert result.items[0].matched_token is not None
    assert result.items[0].match_type == "broad"


def test_competitor_brand_rule_takes_priority() -> None:
    result = scaffold_negatives(
        [_kw("smartbill facturare gratis")],
        _page(),
        competitor_brands=["SmartBill"],
    )
    assert result.items[0].reason_code == "COMPETITOR_BRAND"
    assert result.items[0].matched_token == "SmartBill"


def test_low_commercial_intent_rule() -> None:
    # "registru" nu apare in H1/H2, nu are jeton negativ, e un singur cuvant generic.
    result = scaffold_negatives([_kw("registru")], _page(), competitor_brands=[])
    assert result.items[0].reason_code == "LOW_COMMERCIAL_INTENT"
    assert commercial_intent("registru") < DEFAULT_INTENT_THRESHOLD


def test_commercial_keyword_is_not_negative() -> None:
    result = scaffold_negatives(
        [_kw("pret software contabilitate")], _page(), competitor_brands=[]
    )
    assert result.items == []


def test_keyword_relevant_to_landing_is_kept() -> None:
    # Apare in H1 -> nu devine negativ pe regula de intentie slaba.
    result = scaffold_negatives(
        [_kw("contabilitate online pentru firme")], _page(), competitor_brands=[]
    )
    assert result.items == []


def test_reason_grouping_and_terms() -> None:
    keywords = [_kw("ce este e-factura"), _kw("joburi contabilitate"), _kw("registru")]
    result = scaffold_negatives(keywords, _page(), competitor_brands=[])
    grouped = result.by_reason()
    assert set(grouped) == {
        "TOKEN_INFORMATIONAL",
        "TOKEN_JOB_SEEKER",
        "LOW_COMMERCIAL_INTENT",
    }
    assert set(result.terms()) == {kw.keyword for kw in keywords}
