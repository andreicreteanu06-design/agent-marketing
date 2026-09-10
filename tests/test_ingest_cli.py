"""Test end-to-end pentru comanda ``ingest`` pe furnizori mock."""

from __future__ import annotations

from typer.testing import CliRunner

from ppc_agent.cli import app

runner = CliRunner()


def test_ingest_prints_all_sections() -> None:
    result = runner.invoke(app, ["ingest", "--url", "https://facturarepro.ro"])
    assert result.exit_code == 0
    for section in (
        "PageContext",
        "Seminte organice",
        "GBP",
        "Expansiune Keyword Planner",
        "Cuvinte cheie negative",
    ):
        assert section in result.output


def test_ingest_reports_failed_crawl_without_crashing() -> None:
    result = runner.invoke(app, ["ingest", "--url", "https://facturarepro.ro/timeout"])
    assert result.exit_code == 0
    assert "esec" in result.output
    # Restul pipeline-ului ruleaza chiar daca pagina nu a putut fi accesata.
    assert "Expansiune Keyword Planner" in result.output
