"""Orchestrarea Modulului 1 si redarea rezultatului in consola."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ppc_agent.config import AppConfig
from ppc_agent.ingestion.crawler import crawl
from ppc_agent.ingestion.keywords import expand_keywords
from ppc_agent.ingestion.models import IngestionResult
from ppc_agent.ingestion.negatives import scaffold_negatives
from ppc_agent.ingestion.organic import to_local_signals, to_seed_keywords
from ppc_agent.providers.factory import ProviderFactory

#: Cand nu e configurata nicio locatie reala. Furnizorul ``mock`` il
#: foloseste ca seed determinist; cel ``live`` nu ajunge aici, fiindca
#: primeste locatia din ``Settings`` (vezi apelul de mai jos).
_GBP_LOCATION_PLACEHOLDER = "mock-location"
_TOP_ROWS = 10


def run_ingestion(
    factory: ProviderFactory, url: str, config: AppConfig
) -> IngestionResult:
    """Executa lantul complet al Modulului 1 pentru un domeniu.

    Pasi: crawl -> interogari GSC -> seminte filtrate si scored -> semnale GBP ->
    expansiune Keyword Planner -> schela de cuvinte cheie negative.

    Args:
        factory: Fabrica de furnizori (mock sau live).
        url: Domeniul / pagina de analizat.
        config: Configuratia aplicatiei (geo, limba, branduri concurente).

    Returns:
        Rezultatul de ingestie complet, tipizat.
    """
    page_context = crawl(factory.crawler(), url)

    # Sursele neconfigurate (in ``live``) raman goale, nu opresc ingestia.
    seeds = to_seed_keywords(factory.gsc().top_queries(url)) if factory.configured("gsc") else []
    local_signals = to_local_signals(
        factory.gbp().local_signals(
            config.settings.gbp_location_id or _GBP_LOCATION_PLACEHOLDER
        )
        if factory.configured("gbp")
        else {}
    )

    seed_terms = [seed.query for seed in seeds] or [config.target_domain]
    expanded = (
        expand_keywords(factory.keyword_planner().expand(seed_terms, config.geo, config.language))
        if factory.configured("keyword_planner")
        else []
    )

    negatives = scaffold_negatives(expanded, page_context, config.competitor_brands)

    return IngestionResult(
        url=url,
        page_context=page_context,
        seed_keywords=seeds,
        local_signals=local_signals,
        expanded_keywords=expanded,
        negative_keywords=negatives,
    )


def render_ingestion(result: IngestionResult, console: Console) -> None:
    """Afiseaza rezultatul de ingestie ca sectiuni lizibile in consola."""
    _render_page_context(result, console)
    _render_seeds(result, console)
    _render_local_signals(result, console)
    _render_expansions(result, console)
    _render_negatives(result, console)


def _render_page_context(result: IngestionResult, console: Console) -> None:
    page = result.page_context
    console.print(f"\n[bold]PageContext[/bold]  {result.url}")
    if not page.ok:
        console.print(
            f"  [red]esec:[/red] {page.failure_reason} (status {page.status_code})"
        )
        return
    console.print(f"  title             {page.title}")
    console.print(f"  meta_description  {page.meta_description}")
    console.print(f"  H1                {page.h1}")
    console.print(f"  H2                {page.h2}")
    console.print(f"  CTA               {page.cta_texts}")
    console.print(f"  nav               {page.nav_items}")
    console.print(f"  USP               {page.usp_candidates}")
    if page.is_sparse:
        console.print("  [yellow]pagina pare randata JS (continut sarac)[/yellow]")


def _render_seeds(result: IngestionResult, console: Console) -> None:
    count = len(result.seed_keywords)
    table = Table(title=f"Seminte organice GSC - {count} peste pragul de afisari")
    for name in ("query", "impressions", "ctr", "position", "intent_score"):
        table.add_column(name)
    for seed in result.seed_keywords[:_TOP_ROWS]:
        table.add_row(
            seed.query,
            str(seed.impressions),
            f"{seed.ctr:.3f}",
            f"{seed.position:.1f}",
            f"{seed.intent_score:.3f}",
        )
    console.print(table)


def _render_local_signals(result: IngestionResult, console: Console) -> None:
    signals = result.local_signals
    if signals is None:
        return
    mix = signals.sentiment_mix
    console.print(
        f"\n[bold]GBP[/bold]  {signals.name}  |  {signals.review_count} recenzii  |  "
        f"nota {signals.avg_rating}  |  sentiment {mix}"
    )


def _render_expansions(result: IngestionResult, console: Console) -> None:
    count = len(result.expanded_keywords)
    table = Table(title=f"Expansiune Keyword Planner - {count} cuvinte")
    columns = (
        "keyword",
        "avg_monthly_searches",
        "competition",
        "bid_low",
        "bid_high",
        "match",
    )
    for name in columns:
        table.add_column(name)
    for keyword in result.expanded_keywords[:_TOP_ROWS]:
        table.add_row(
            keyword.keyword,
            str(keyword.avg_monthly_searches),
            f"{keyword.competition:.2f}",
            f"{keyword.low_top_bid}",
            f"{keyword.high_top_bid}",
            keyword.match_type_suggestion,
        )
    console.print(table)


def _render_negatives(result: IngestionResult, console: Console) -> None:
    negatives = result.negative_keywords
    grouped = negatives.by_reason()
    console.print(
        f"\n[bold]Cuvinte cheie negative[/bold]  -  {len(negatives.items)} total"
    )
    for reason, entries in sorted(grouped.items()):
        sample = ", ".join(entry.term for entry in entries[:5])
        console.print(f"  {reason:<22} {len(entries):>3}  -  {sample}")
