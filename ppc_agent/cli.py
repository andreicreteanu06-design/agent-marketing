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

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from ppc_agent.alignment.pipeline import render_alignment, run_alignment
from ppc_agent.config import AppConfig, load_config
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.models import OmniPlatform
from ppc_agent.copywriter.pipeline import append_to_queue, render_copy, run_copy
from ppc_agent.copywriter.swipe import default_swipe_path
from ppc_agent.creative.creative_pipeline import (
    generate_and_save_storyboard,
    generate_full_ad_creative,
    render_creative,
    render_storyboard,
)
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.decision.fatigue_monitor import load_ad_performance_states
from ppc_agent.decision.pipeline import render_plan, run_plan
from ppc_agent.errors import (
    ApprovalRequiredError,
    CopywriterError,
    FatigueInputError,
    PpcAgentError,
    SetupRequiredError,
    SpendLimitExceeded,
    StoryboardValidationError,
    SwipeIngestError,
    TikTokIngestError,
    TtsError,
    VideoAssemblyError,
)
from ppc_agent.guardrails.approval_gate import ApprovalGate
from ppc_agent.guardrails.pipeline import (
    build_fatigue_changes,
    build_proposed_changes,
    latest_changeset_path,
    render_changeset,
    render_fatigue_evaluations,
)
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent.ingestion.pipeline import render_ingestion, run_ingestion
from ppc_agent.ingestion.swipe_ingestion import render_swipe_ingest, run_swipe_ingest
from ppc_agent.ingestion.tiktok_ingestion import (
    LIBRARY_FILENAME,
    render_tiktok_ingest,
    run_tiktok_ingest,
)
from ppc_agent.providers.factory import ProviderFactory

app = typer.Typer(
    name="ppc-agent",
    help="Agent PPC pentru marketeri: Google Ads, Meta Ads si TikTok Ads cu guardrails HITL.",
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
    platform: Annotated[
        Literal["google", "tiktok"],
        typer.Option("--platform", help="google (16:9) sau tiktok (script UGC, 9:16)."),
    ] = "google",
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
            platform=platform,
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


@app.command("build-storyboard")
def build_storyboard(
    keyword: Annotated[
        str, typer.Option("--keyword", help="Cuvantul cheie / nisa tinta.")
    ],
    usp: Annotated[
        str, typer.Option("--usp", help="Propunerea unica de valoare (optional).")
    ] = "",
    config: _ConfigOption = "config.yaml",
) -> None:
    """Genereaza un storyboard video programatic (Lead Performance Creative Director).

    LLM-ul regizeaza, nu doar scrie: scene cronometrate, text pozitionat in
    zone sigure, piste audio separate. Validat determinist (ritm/tipografie/
    CTA/timeline) inainte de salvare; scrie storyboard_*.json in
    creative_output/. Fara b-roll/TTS/asamblare video (spre deosebire de
    'build-creative') - e un document de pre-productie, nu un .mp4 final.
    """
    app_config = load_config(config)
    factory = CreativeFactory(app_config)
    try:
        storyboard, path = generate_and_save_storyboard(
            factory.llm(),
            product_usp=usp or f"Solutie pentru {keyword}, rapid si fara batai de cap",
            target_keyword=keyword,
            output_dir=Path.cwd() / "creative_output",
        )
    except SetupRequiredError as exc:
        console.print(f"[red]clientul LLM nu e pregatit:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except StoryboardValidationError as exc:
        console.print(f"[red]storyboard invalid:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except CopywriterError as exc:
        console.print(f"[red]nu s-a putut genera:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    render_storyboard(storyboard, path, console)


@app.command()
def ingest_tiktok(
    input_path: Annotated[
        str,
        typer.Option("--input", help="Cale catre CSV sau JSON cu anunturi TikTok dovedite."),
    ],
) -> None:
    """Valideaza anunturi TikTok si le adauga in tiktok_swipe_library.json.

    Fara LLM: intrarile sunt deja structurate (nisa/format/hook/cta), doar se
    valideaza si se deduplica dupa ad_id. Biblioteca alimenteaza RAG-ul folosit
    de 'copy'/'build-creative' pentru scripturi TikTok.
    """
    try:
        added = run_tiktok_ingest(input_path, Path.cwd())
    except TikTokIngestError as exc:
        console.print(f"[red]ingestia a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    render_tiktok_ingest(added, Path.cwd() / LIBRARY_FILENAME, console)


@app.command("ingest-swipes")
def ingest_swipes(
    csv_path: Annotated[
        str, typer.Option("--csv", help="Cale catre CSV cu anunturi dovedite.")
    ],
    platform: Annotated[
        OmniPlatform,
        typer.Option("--platform", help="Platforma tuturor randurilor din CSV."),
    ],
) -> None:
    """Valideaza anunturi si le adauga in omnichannel_swipe_library (swipe_file.json).

    Fara LLM: intrarile sunt deja structurate, doar se valideaza si deduplica
    dupa ad_id (derivat din continut). Scrie direct in swipe_file.json (spre
    deosebire de 'ingest-tiktok', care acumuleaza intr-un fisier separat) —
    biblioteca omnicanal alimenteaza RAG-ul folosit de 'copy-omnichannel'.
    """
    try:
        added = run_swipe_ingest(csv_path, platform)
    except SwipeIngestError as exc:
        console.print(f"[red]ingestia a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    render_swipe_ingest(added, default_swipe_path(), console)


@app.command("copy-omnichannel")
def copy_omnichannel(
    niche: Annotated[
        str, typer.Option("--niche", help="Nisa / segmentul de piata tinta.")
    ],
    usp: Annotated[
        str, typer.Option("--usp", help="Propunerea unica de valoare a produsului.")
    ],
    target_platform: Annotated[
        OmniPlatform,
        typer.Option("--target-platform", help="google, meta sau tiktok."),
    ] = "google",
    config: _ConfigOption = "config.yaml",
) -> None:
    """Genereaza copy omnicanal (RAG pe nisa + platforma, swipe unificat).

    Spre deosebire de 'copy' (declansator emotional, google/tiktok), aici
    recuperarea e dupa nisa filtrata strict pe platforma, cu prompt dedicat per
    canal (Google/Meta/TikTok). Doar afiseaza rezultatul - fara coada HITL
    proprie in v1 (nu se publica nimic).
    """
    app_config = load_config(config)
    generator = AdCopyGenerator(CreativeFactory(app_config).llm())
    try:
        result = generator.generate_omnichannel_copy(usp, niche, target_platform)
    except SetupRequiredError as exc:
        console.print(f"[red]clientul LLM nu e pregatit:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except CopywriterError as exc:
        console.print(f"[red]nu s-a putut genera:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"\n[bold]Copy omnicanal[/bold] ({target_platform})")
    for key, value in result.items():
        console.print(f"  {key}: {value}", markup=False)


@app.command("check-fatigue")
def check_fatigue(
    input_path: Annotated[
        str,
        typer.Option("--input", help="JSON cu o lista de AdPerformanceState."),
    ],
    config: _ConfigOption = "config.yaml",
) -> None:
    """Monitorul de oboseala: Kill Rules (anunturi noi) + Pruning Switch (fatigued).

    Fara sursa live: niciun provider mock din proiect nu produce inca acest
    nivel de detaliu per-anunt (frecventa, CTR/CPA de baza, zile proaste) - ca
    la 'ingest-tiktok', fisierul e furnizat de operator. Anunturile cu verdict
    de oprire (PAUSE_HARD/PAUSE_PROVISIONAL/PAUSE_REPLACE) intra intr-un
    proposed_changes_*.json obisnuit - 'execute --confirm' functioneaza
    neschimbat, fara nicio adaptare pentru acest flux.
    """
    app_config = load_config(config)
    try:
        ads = load_ad_performance_states(input_path)
    except FatigueInputError as exc:
        console.print(f"[red]citirea a esuat:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    now = datetime.now(tz=UTC)
    render_fatigue_evaluations(ads, now, console)

    changes = build_fatigue_changes(ads, now)
    if not changes:
        console.print("\n[dim]niciun anunt de oprit[/dim]")
        return

    gate = ApprovalGate(
        account=_account_label(app_config),
        spend_limiter=AbsoluteSpendLimiter(app_config.budget.max_daily_spend),
        output_dir=Path.cwd(),
    )
    gate.propose_many(changes)
    path = gate.flush()
    render_changeset(gate.build_changeset(), path, console)
    console.print(
        f"\n[green]scris[/green] {path.name} - revizuieste-l, apoi ruleaza:\n"
        f"  python -m ppc_agent.cli execute --changeset {path.name} --confirm"
    )


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
