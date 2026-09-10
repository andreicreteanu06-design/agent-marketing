"""Interfata linie de comanda a agentului PPC.

Comenzi: ``ingest``, ``plan``, ``propose``, ``execute``, ``status``.

Rulare::

    python -m ppc_agent.cli --help
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from ppc_agent.config import load_config
from ppc_agent.ingestion.pipeline import render_ingestion, run_ingestion
from ppc_agent.providers.factory import ProviderFactory

app = typer.Typer(
    name="ppc-agent",
    help="Agent PPC pentru marketeri: Google Ads si Meta Ads cu guardrails HITL.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_NOT_IMPLEMENTED = "[yellow]neimplementat inca[/yellow]"

_ConfigOption = Annotated[
    str, typer.Option("--config", help="Cale catre fisierul de configurare YAML.")
]


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
    console.print(f"plan config={config}: {_NOT_IMPLEMENTED}")


@app.command()
def propose(config: _ConfigOption = "config.yaml") -> None:
    """Modulul 4: scrie proposed_changes.json. Nu aplica nicio modificare."""
    console.print(f"propose config={config}: {_NOT_IMPLEMENTED}")


@app.command()
def execute(
    changeset: Annotated[
        str, typer.Option("--changeset", help="Cale catre proposed_changes.json.")
    ],
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirmare umana explicita.")
    ] = False,
) -> None:
    """Modulul 4: executa un set de modificari confirmat. In v1 doar simuleaza apelurile."""
    console.print(
        f"execute changeset={changeset} confirm={confirm}: {_NOT_IMPLEMENTED}"
    )


@app.command()
def status(config: _ConfigOption = "config.yaml") -> None:
    """Afiseaza setul de modificari in asteptare si modul curent al furnizorilor."""
    console.print(f"status config={config}: {_NOT_IMPLEMENTED}")


if __name__ == "__main__":
    app()
