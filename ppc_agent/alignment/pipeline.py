"""Orchestrarea Modulului 3 si redarea rezultatului in consola."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from rich.console import Console
from rich.table import Table

from ppc_agent.alignment.meta_liquidity import consolidation_plan
from ppc_agent.alignment.models import AdSet, AlignmentResult
from ppc_agent.alignment.quality_score import analyze_ad_groups
from ppc_agent.alignment.samples import sample_ad_groups
from ppc_agent.config import AppConfig
from ppc_agent.ingestion.crawler import crawl
from ppc_agent.ingestion.models import PageContext
from ppc_agent.providers.factory import ProviderFactory

_META_ACCOUNT_PLACEHOLDER = "mock-account"


def _ad_sets_from_frame(frame: pd.DataFrame) -> list[AdSet]:
    out: list[AdSet] = []
    for record in frame.to_dict(orient="records"):
        out.append(
            AdSet(
                ad_set_id=str(record["ad_set_id"]),
                name=str(record["name"]),
                audience_def=str(record["audience_def"]),
                weekly_conversions=float(record["weekly_conversions"]),
                weekly_spend=Decimal(str(record["weekly_spend"])),
                learning_phase=bool(record["learning_phase"]),
            )
        )
    return out


def run_alignment(
    factory: ProviderFactory,
    config: AppConfig,
    page_context: PageContext | None = None,
) -> AlignmentResult:
    """Executa Modulul 3: rapoarte Quality Score + plan de lichiditate Meta.

    Args:
        factory: Fabrica de furnizori (mock sau live).
        config: Configuratia aplicatiei (domeniu tinta, prag Meta).
        page_context: Context de pagina deja obtinut; daca lipseste, se face crawl
            pe ``config.target_domain``.

    Returns:
        Rezultatul de aliniere.
    """
    page = page_context or crawl(factory.crawler(), config.target_domain)
    reports = analyze_ad_groups(sample_ad_groups(), page)

    ad_sets = _ad_sets_from_frame(factory.meta().ad_sets(_META_ACCOUNT_PLACEHOLDER))
    liquidity = consolidation_plan(ad_sets, config.meta.target_weekly_conversions)

    return AlignmentResult(quality_score_reports=reports, liquidity_plan=liquidity)


def render_alignment(result: AlignmentResult, console: Console) -> None:
    """Afiseaza rapoartele Quality Score si planul de lichiditate in consola."""
    _render_quality_score(result, console)
    _render_liquidity(result, console)


def _render_quality_score(result: AlignmentResult, console: Console) -> None:
    console.print("\n[bold]Quality Score - aliniere copy / keyword / landing[/bold]")
    table = Table()
    for name in ("grup", "keyword", "scor", "CTR", "relevanta", "landing", "flag"):
        table.add_column(name)
    for report in result.quality_score_reports:
        table.add_row(
            report.name,
            report.keyword,
            f"{report.score:.1f}",
            report.expected_ctr,
            report.ad_relevance,
            report.landing_page_experience,
            "!" if report.flagged else "",
        )
    console.print(table)
    for report in result.quality_score_reports:
        if report.suggestions:
            console.print(f"  [dim]{report.name}:[/dim]")
            for suggestion in report.suggestions:
                console.print(f"    - {suggestion}")


def _render_liquidity(result: AlignmentResult, console: Console) -> None:
    plan = result.liquidity_plan
    console.print(
        f"\n[bold]Lichiditate Meta[/bold]  (prag {plan.target_weekly_conversions} "
        f"conversii/saptamana, CBO {'da' if plan.recommend_cbo else 'nu'})"
    )
    if plan.untouched_ids:
        console.print(f"  neatinse (deja sanatoase): {', '.join(plan.untouched_ids)}")
    table = Table()
    for name in ("set consolidat", "surse", "proiectie/sapt", "atinge prag", "iesire invatare"):
        table.add_column(name)
    for merge in plan.merges:
        table.add_row(
            merge.merged_id,
            ", ".join(merge.source_ids),
            f"{merge.projected_weekly_conversions:.0f}",
            "da" if merge.clears_threshold else "nu",
            "-" if merge.learning_exit_days is None else f"~{merge.learning_exit_days:.0f} zile",
        )
    console.print(table)
    for merge in plan.merges:
        for warning in merge.warnings:
            console.print(f"  [yellow]{merge.merged_id}: {warning}[/yellow]")
    for warning in plan.warnings:
        console.print(f"  [yellow]{warning}[/yellow]")
