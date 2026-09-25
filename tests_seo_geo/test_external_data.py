"""PageSpeed Insights: textul pentru oameni si aceleasi metrici ca numere, fara retea."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from seo_geo_agent.external_data import fetch_pagespeed_insights


def _lighthouse(audits: dict[str, Any], score: float = 0.38) -> dict[str, Any]:
    return {
        "lighthouseResult": {
            "categories": {"performance": {"score": score}},
            "audits": audits,
        }
    }


def _fetch(payload: dict[str, Any], seen: list[httpx.Request]) -> dict[str, Any] | None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    return asyncio.run(
        fetch_pagespeed_insights("https://autofix.ro/", transport=httpx.MockTransport(handler))
    )


def test_pagespeed_returns_numeric_core_web_vitals_next_to_the_display_text() -> None:
    seen: list[httpx.Request] = []
    payload = _lighthouse(
        {
            "largest-contentful-paint": {"displayValue": "4.8 s", "numericValue": 4830.4},
            "cumulative-layout-shift": {"displayValue": "0.312", "numericValue": 0.31234},
            "total-blocking-time": {"displayValue": "820 ms", "numericValue": 820.2},
        }
    )

    result = _fetch(payload, seen)

    assert result == {
        "performance_score": 38,
        "largest_contentful_paint": "4.8 s",
        "cumulative_layout_shift": "0.312",
        "total_blocking_time": "820 ms",
        "lcp_ms": 4830.0,
        "cls": 0.312,
        "tbt_ms": 820.0,
    }
    [request] = seen
    assert request.url.host == "www.googleapis.com"
    assert request.url.params["strategy"] == "mobile"
    assert request.url.params["url"] == "https://autofix.ro/"


def test_a_missing_metric_is_none_not_zero() -> None:
    result = _fetch(
        _lighthouse({"largest-contentful-paint": {"displayValue": "2.1 s", "numericValue": True}}),
        [],
    )

    assert result is not None
    assert (result["lcp_ms"], result["cls"], result["tbt_ms"]) == (None, None, None)
