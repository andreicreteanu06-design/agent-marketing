"""Orchestrarea Modulului 2 si redarea rezultatului in consola."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from rich.console import Console
from rich.table import Table

from ppc_agent.config import AppConfig
from ppc_agent.decision.attribution import Journey, attribute
from ppc_agent.decision.budget import ThompsonBudgetAllocator
from ppc_agent.decision.models import ArmStats, PlanResult
from ppc_agent.providers.factory import ProviderFactory

_CUSTOMER_PLACEHOLDER = "mock-customer"
_DEFAULT_SEED = 20260101
_DEFAULT_SAMPLES = 20_000


def _arms_from_performance(frame: pd.DataFrame) -> list[ArmStats]:
    arms: list[ArmStats] = []
    for record in frame.to_dict(orient="records"):
        arms.append(
            ArmStats(
                arm_id=str(record["arm_id"]),
                name=str(record["name"]),
                clicks=int(record["clicks"]),
                conversions=int(record["conversions"]),
                cost=Decimal(str(record["cost"])),
            )
        )
    return arms


def run_plan(
    factory: ProviderFactory,
    config: AppConfig,
    *,
    seed: int | None = _DEFAULT_SEED,
    n_samples: int = _DEFAULT_SAMPLES,
) -> PlanResult:
    """Executa Modulul 2: alocare de buget si atribuire Markov.

    Args:
        factory: Fabrica de furnizori (mock sau live).
        config: Configuratia aplicatiei (buget, praguri).
        seed: Seed pentru esantionarea Thompson (reproducibilitate CLI si teste).
        n_samples: Numarul de esantioane Monte Carlo per posterior.

    Returns:
        Planul complet: alocare de buget + rezultatul atribuirii.
    """
    ads = factory.google_ads()
    arms = _arms_from_performance(ads.campaign_performance(_CUSTOMER_PLACEHOLDER))

    allocator = ThompsonBudgetAllocator(
        min_arm_daily_spend=config.budget.min_arm_daily_spend
    )
    budget_plan = allocator.allocate(
        arms,
        float(config.budget.max_daily_spend),
        n_samples=n_samples,
        seed=seed,
    )

    journeys = [Journey.from_tokens(path) for path in ads.conversion_paths(_CUSTOMER_PLACEHOLDER)]
    attribution = attribute(journeys)

    return PlanResult(budget_plan=budget_plan, attribution=attribution)


def render_plan(result: PlanResult, console: Console) -> None:
    """Afiseaza planul de buget si tabelul de atribuire in consola."""
    _render_budget(result, console)
    _render_attribution(result, console)


def _render_budget(result: PlanResult, console: Console) -> None:
    plan = result.budget_plan
    console.print(
        f"\n[bold]Alocare buget - Thompson Sampling[/bold]  "
        f"(buget {plan.daily_budget} / zi, {plan.n_samples} esantioane, seed {plan.seed})"
    )
    table = Table()
    for name in ("campanie", "P(cel mai bun)", "cota", "buget/zi", "nota"):
        table.add_column(name)
    for item in plan.allocations:
        table.add_row(
            item.name,
            f"{item.win_probability:.3f}",
            f"{item.final_share:.3f}",
            f"{item.daily_budget}",
            item.note or "",
        )
    console.print(table)
    console.print(f"  total alocat: {plan.total_allocated}")


def _render_attribution(result: PlanResult, console: Console) -> None:
    attribution = result.attribution
    console.print(
        f"\n[bold]Atribuire Markov[/bold]  "
        f"(P(conversie) de baza {attribution.base_conversion_probability:.4f}, "
        f"{attribution.total_conversions:.0f} conversii)"
    )
    table = Table()
    for name in ("canal", "efect eliminare", "conversii Markov", "conversii last-click"):
        table.add_column(name)
    for channel in attribution.channels:
        table.add_row(
            channel.channel,
            f"{channel.removal_effect:.4f}",
            f"{channel.markov_conversions:.2f}",
            f"{channel.last_click_conversions:.2f}",
        )
    console.print(table)
    console.print(
        "  [dim]Markov inlocuieste last-click / data-driven: coloana finala e doar "
        "pentru comparatie.[/dim]"
    )
