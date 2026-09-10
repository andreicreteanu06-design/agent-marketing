"""Teste pentru crawler: parsare HTML, robots.txt, 404, timeout, pagina JS."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppc_agent.ingestion.crawler import base_origin, build_page_context, crawl
from ppc_agent.providers.mock.crawler import MockCrawlerProvider


@pytest.fixture
def landing_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "landing.html").read_text(encoding="utf-8")


@pytest.fixture
def spa_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "spa.html").read_text(encoding="utf-8")


def test_build_page_context_extracts_structure(landing_html: str) -> None:
    page = build_page_context(landing_html, "https://contapp.ro", 200)

    assert page.ok
    assert page.title == "ContApp - Contabilitate online pentru PFA si SRL"
    assert "contabilitatea firmei" in page.meta_description
    assert page.h1 == ["Contabilitate online, fara batai de cap"]
    assert "Functii principale" in page.h2
    assert "Cat costa" in page.h2
    assert page.h3 == ["Declaratii automate", "e-Factura"]
    assert page.nav_items == ["Acasa", "Functii", "Preturi", "Contact"]
    assert not page.is_sparse


def test_build_page_context_finds_ctas(landing_html: str) -> None:
    page = build_page_context(landing_html, "https://contapp.ro", 200)
    assert "Incepe gratuit" in page.cta_texts
    assert "Solicita o demonstratie" in page.cta_texts
    assert "Termeni" not in page.cta_texts


def test_build_page_context_usp_candidates(landing_html: str) -> None:
    page = build_page_context(landing_html, "https://contapp.ro", 200)
    assert any("Automatizeaza declaratiile" in usp for usp in page.usp_candidates)


def test_sparse_page_is_flagged(spa_html: str) -> None:
    page = build_page_context(spa_html, "https://app.contapp.ro", 200)
    assert page.ok
    assert page.is_sparse


def test_crawl_handles_404() -> None:
    page = crawl(MockCrawlerProvider(), "https://contapp.ro/pagina-inexistent")
    assert not page.ok
    assert page.status_code == 404
    assert page.failure_reason == "not_found"


def test_crawl_handles_timeout() -> None:
    page = crawl(MockCrawlerProvider(), "https://contapp.ro/timeout")
    assert not page.ok
    assert page.failure_reason == "CrawlTimeoutError"


def test_crawl_respects_robots_disallow() -> None:
    page = crawl(MockCrawlerProvider(), "https://blocat.example.com/oferta")
    assert not page.ok
    assert page.failure_reason == "blocat_de_robots_txt"


def test_crawl_success_parses_mock_landing() -> None:
    page = crawl(MockCrawlerProvider(), "https://facturarepro.ro")
    assert page.ok
    assert page.h1
    assert page.cta_texts


def test_base_origin() -> None:
    assert base_origin("https://sub.exemplu.ro/cale?x=1") == "https://sub.exemplu.ro"
