"""Interfata linie de comanda a agentului PPC.

Comenzi: ``ingest``, ``plan``, ``propose``, ``execute``, ``status``.

Flux tipic::

    python -m ppc_agent.cli ingest --url https://exemplu.ro
    python -m ppc_agent.cli plan
    python -m ppc_agent.cli propose          # scrie proposed_changes_*.json
    python -m ppc_agent.cli status           # arata setul in asteptare
    python -m ppc_agent.cli execute --changeset proposed_changes_XXX.json --confirm
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ppc_agent.alignment.pipeline import render_alignment, run_alignment
from ppc_agent.config import AppConfig, load_config
from ppc_agent.decision.pipeline import render_plan, run_plan
from ppc_agent.errors import ApprovalRequiredError, SpendLimitExceeded
from ppc_agent.guardrails.approval_gate import ApprovalGate
from ppc_agent.guardrails.pipeline import (
    build_proposed_changes,
    latest_changeset_path,
    render_changeset,
)
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent.ingestion.pipeline import render_ingestion, run_ingestion
from ppc_agent.providers.factory import ProviderFactory

app = typer.Typer(
    name="ppc-agent",
    help="Agent PPC pentru marketeri: Google Ads si Meta Ads cu guardrails HITL.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_ConfigOption = Annotated[
    str, typer.Option("--config", help="Cale catre fisierul de configurare YAML.")
]
_MOCK_ACCOUNT = "mock-account"


def _account_label(config: AppConfig) -> str:
    mode = "live" if config.provider_mode.value == "live" else "mock"
    return f"{mode}:{config.settings.google_ads_login_customer_id or _MOCK_ACCOUNT}"


@app.command()
def ingest(
    url: Annotated[str, typer.Option("--url", help="Domeniul de analizat.")],
    config: _ConfigOption = "config.yaml",
) -> None:
    """Modulul 1: crawling domeniu, date organice (GSC/GBP), expansiune cuvinte cheie."""
    app_config = load_config(config)
    factory = ProviderFactory(app_config)
    result = run_ingestion(factory, url, app_config)
    render_ingestion(result, console)


@app.command()
def plan(config: _ConfigOption = "config.yaml") -> None:
    """Modulele 2-3: alocare buget, atribuire Markov, Quality Score, lichiditate Meta."""
    app_config = load_config(config)
    factory = ProviderFactory(app_config)
    render_plan(run_plan(factory, app_config), console)
    render_alignment(run_alignment(factory, app_config), console)


@app.command()
def propose(config: _ConfigOption = "config.yaml") -> None:
    """Modulul 4: compileaza modificarile din Modulele 1-3 in proposed_changes.json.

    Nu se aplica nimic. Daca cheltuiala zilnica totala depaseste limita, fisierul
    nici nu se scrie.
    """
    app_config = load_config(config)
    factory = ProviderFactory(app_config)

    ingestion = run_ingestion(factory, app_config.target_domain, app_config)
    decision = run_plan(factory, app_config)
    alignment = run_alignment(factory, app_config, ingestion.page_context)

    changes = build_proposed_changes(
        budget_plan=decision.budget_plan,
        negatives=ingestion.negative_keywords,
        liquidity=alignment.liquidity_plan,
    )

    gate = ApprovalGate(
        account=_account_label(app_config),
        spend_limiter=AbsoluteSpendLimiter(app_config.budget.max_daily_spend),
        output_dir=Path.cwd(),
    )
    gate.propose_many(changes)

    try:
        path = gate.flush()
    except SpendLimitExceeded as exc:
        console.print(f"[red]set respins, nimic scris:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    render_changeset(gate.build_changeset(), path, console)
    console.print(
        f"\n[green]scris[/green] {path.name} - revizuieste-l, apoi ruleaza:\n"
        f"  python -m ppc_agent.cli execute --changeset {path.name} --confirm"
    )


@app.command()
def status(config: _ConfigOption = "config.yaml") -> None:
    """Afiseaza cel mai recent set de modificari in asteptare si modul furnizorilor."""
    app_config = load_config(config)
    console.print(f"mod furnizori: [bold]{app_config.provider_mode.value}[/bold]")

    path = latest_changeset_path(Path.cwd())
    if path is None:
        console.print("niciun set de modificari in asteptare (ruleaza 'propose')")
        return
    render_changeset(ApprovalGate.load(path), path, console)


@app.command()
def execute(
    changeset: Annotated[
        str, typer.Option("--changeset", help="Cale catre proposed_changes_*.json.")
    ],
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirmare umana explicita.")
    ] = False,
    config: _ConfigOption = "config.yaml",
) -> None:
    """Modulul 4: executa un set de modificari confirmat. In v1 doar simuleaza apelurile."""
    app_config = load_config(config)
    gate = ApprovalGate(
        account=_account_label(app_config),
        spend_limiter=AbsoluteSpendLimiter(app_config.budget.max_daily_spend),
    )
    try:
        report = gate.execute(changeset, confirmed=confirm)
    except ApprovalRequiredError as exc:
        console.print(f"[red]blocat:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]executat (simulat)[/green]: {len(report.simulated_calls)} apeluri, "
        f"applied={report.applied}"
    )
    for call in report.simulated_calls:
        console.print(f"  {call}")


if __name__ == "__main__":
    app()
