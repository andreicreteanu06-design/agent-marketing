"""Interfata linie de comanda a agentului PPC.

Comenzi: ``ingest``, ``plan``, ``copy``, ``propose``, ``execute``, ``status``.

Flux tipic::

    python -m ppc_agent.cli ingest --url https://exemplu.ro
    python -m ppc_agent.cli plan
    python -m ppc_agent.cli copy --keyword "program facturare" --usp "..." --trigger fomo
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
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.pipeline import append_to_queue, render_copy, run_copy
from ppc_agent.creative.creative_pipeline import generate_full_ad_creative, render_creative
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.decision.pipeline import render_plan, run_plan
from ppc_agent.errors import (
    ApprovalRequiredError,
    CopywriterError,
    PpcAgentError,
    SetupRequiredError,
    SpendLimitExceeded,
    TtsError,
    VideoAssemblyError,
)
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
def copy(
    keyword: Annotated[
        str, typer.Option("--keyword", help="Cuvantul cheie exact-match.")
    ],
    usp: Annotated[
        str, typer.Option("--usp", help="Propunerea unica de valoare a produsului.")
    ],
    trigger: Annotated[
        str,
        typer.Option(
            "--trigger", help="Declansator emotional: pas / status / fomo / aida."
        ),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Afiseaza fara sa adaugi in coada.")
    ] = False,
    config: _ConfigOption = "config.yaml",
) -> None:
    """Genereaza copy emotional (RAG local pe swipe_file.json) si il pune in coada HITL.

    Nimic nu se publica online: copy-ul se adauga in proposed_ads_queue.json pentru
    aprobare manuala. Clientul LLM (mock sau Ollama live) e ales dupa PPC_PROVIDER_MODE.
    """
    app_config = load_config(config)
    generator = AdCopyGenerator(CreativeFactory(app_config).llm())
    try:
        entry = run_copy(
            generator,
            product_usp=usp,
            target_keyword=keyword,
            emotion_trigger=trigger,
        )
    except SetupRequiredError as exc:
        console.print(f"[red]clientul LLM nu e pregatit:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except CopywriterError as exc:
        console.print(f"[red]nu s-a putut genera:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    render_copy(entry, console)
    if dry_run:
        console.print("\n[dim]--dry-run: nimic adaugat in coada[/dim]")
        return
    path = append_to_queue(entry, Path.cwd())
    console.print(f"\n[green]adaugat in[/green] {path.name} (status: pending_review)")


@app.command()
def build_creative(
    keyword: Annotated[
        str, typer.Option("--keyword", help="Cuvantul cheie exact-match al anuntului.")
    ],
    broll: Annotated[
        str, typer.Option("--broll", help="Cale catre video-ul de fundal (b-roll).")
    ],
    usp: Annotated[
        str, typer.Option("--usp", help="Propunerea unica de valoare (optional).")
    ] = "",
    trigger: Annotated[
        str, typer.Option("--trigger", help="Declansator emotional: pas/status/fomo/aida.")
    ] = "aida",
    config: _ConfigOption = "config.yaml",
) -> None:
    """Modulul 5: copy emotional -> voce (Fish Speech) -> video (Flick) -> .mp4.

    Totul offline in modul mock; nimic nu se publica. Afiseaza calea .mp4 finala.
    """
    app_config = load_config(config)
    factory = CreativeFactory(app_config)
    try:
        result = generate_full_ad_creative(
            factory.llm(),
            factory.tts(),
            factory.video(),
            keyword=keyword,
            raw_broll_path=broll,
            emotion_trigger=trigger,
            product_usp=usp or None,
            output_dir=Path.cwd() / "creative_output",
        )
    except TtsError as exc:
        console.print(f"[red]sinteza vocala (TTS) a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except VideoAssemblyError as exc:
        console.print(f"[red]asamblarea video a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except PpcAgentError as exc:
        console.print(f"[red]generarea creatiei a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    render_creative(result, console)
    console.print(f"\n{result.mp4_path}")


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
        kelly=decision.kelly,
    )

    # Plafonul limitatorului = plafonul dimensionat Kelly (poate depasi
    # config.budget.max_daily_spend, dar niciodata HARD_CEILING).
    gate = ApprovalGate(
        account=_account_label(app_config),
        spend_limiter=AbsoluteSpendLimiter(decision.kelly.sized_daily_cap),
        output_dir=Path.cwd(),
    )
    gate.propose_many(changes)

    try:
        path = gate.flush()
    except SpendLimitExceeded as exc:
        console.print(f"[red]set respins, nimic scris:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[dim]{decision.kelly.rationale}[/dim]"
    )

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
