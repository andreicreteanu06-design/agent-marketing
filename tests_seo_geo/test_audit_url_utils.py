"""Normalizarea URL-urilor si politica anti-SSRF.

Testam invariantele pe care se sprijina tot crawl-ul: deduplicarea corecta a
URL-urilor, granita de origine, si refuzul tintelor interne. Nu retestam
``urllib.parse``.
"""

from __future__ import annotations

import asyncio

import pytest

from seo_geo_agent.audit import url_policy
from seo_geo_agent.audit.url_policy import (
    CrawlTargetBlockedError,
    is_crawlable_url,
    normalize_and_validate_start_url,
)
from seo_geo_agent.audit.url_utils import (
    canonical_url_key,
    detect_url_template,
    is_same_origin,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Exemplu.RO/a?b=2&a=1#frag", "https://exemplu.ro/a?a=1&b=2"),
        ("https://exemplu.ro:443/a", "https://exemplu.ro/a"),
        ("ftp://exemplu.ro/a", None),
        ("nu e un url", None),
    ],
)
def test_normalize_url_normalizeaza_si_respinge(raw: str, expected: str | None) -> None:
    assert normalize_url(raw) == expected


def test_normalize_url_pastreaza_slash_ul_final() -> None:
    """Fara asta, /docs si /docs/ ar colapsa si crawl-ul ar intra in bucla 508.

    Vezi comentariul din ``url_utils.normalize_url`` - e capcana din original.
    """
    assert normalize_url("https://exemplu.ro/docs/") == "https://exemplu.ro/docs/"
    assert normalize_url("https://exemplu.ro/docs") == "https://exemplu.ro/docs"


def test_normalize_url_rezolva_relativ_fata_de_baza() -> None:
    assert normalize_url("../b", "https://exemplu.ro/a/c") == "https://exemplu.ro/b"


def test_canonical_url_key_ignora_www_si_schema() -> None:
    assert canonical_url_key("http://www.exemplu.ro/a") == canonical_url_key("https://exemplu.ro/a")


@pytest.mark.parametrize(
    ("url", "origin", "expected"),
    [
        ("https://www.exemplu.ro/a", "https://exemplu.ro", True),
        ("https://exemplu.ro/a", "http://exemplu.ro", True),  # upgrade http -> https
        ("https://altul.ro/a", "https://exemplu.ro", False),
        ("https://sub.exemplu.ro/a", "https://exemplu.ro", False),
    ],
)
def test_is_same_origin(url: str, origin: str, expected: bool) -> None:
    assert is_same_origin(url, origin) is expected


def test_detect_url_template_grupeaza_paginile_din_sablon() -> None:
    assert detect_url_template("/blog/articolul-meu-grozav") == "/blog/:slug"
    assert detect_url_template("/produse/12345") == "/produse/:id"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/intern",
        "http://ceva.internal/a",
        "file:///etc/passwd",
    ],
)
def test_is_crawlable_url_refuza_tintele_interne(url: str) -> None:
    assert is_crawlable_url(url) is False


def test_start_url_primeste_https_daca_lipseste_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rezolvarea DNS e inlocuita: suita ruleaza fara retea (vezi README)."""

    async def _no_dns(_hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", _no_dns)
    assert asyncio.run(normalize_and_validate_start_url("exemplu.ro")) == "https://exemplu.ro"


def test_start_url_blocat_pentru_host_intern() -> None:
    """IP privat scris literal: refuzat fara sa fie nevoie de vreun lookup."""
    with pytest.raises(CrawlTargetBlockedError):
        asyncio.run(normalize_and_validate_start_url("http://192.168.1.1/"))
