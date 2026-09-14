"""Orchestrarea Modulului 2 si redarea rezultatului in consola."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from rich.console import Console
from rich.table import Table

from ppc_agent.config import AppConfig
from ppc_agent.decision.attribution import Journey, attribute
from ppc_agent.decision.budget import ThompsonBudgetAllocator
from ppc_agent.decision.budget_strategy import recommend_arm_capacity
from ppc_agent.decision.kelly_sizing import size_daily_budget
from ppc_agent.decision.models import ArmCapacityAdvice, ArmStats, PlanResult
from ppc_agent.guardrails.spend_limiter import HARD_CEILING
from ppc_agent.providers.factory import ProviderFactory

_CUSTOMER_PLACEHOLDER = "mock-customer"
_ADVERTISER_PLACEHOLDER = "mock-advertiser"
_META_ACCOUNT_PLACEHOLDER = "mock-account"
_DEFAULT_SEED = 20260101
_DEFAULT_SAMPLES = 20_000


def _arms_from_performance(frame: pd.DataFrame, *, platform: str = "google_ads") -> list[ArmStats]:
    arms: list[ArmStats] = []
    for record in frame.to_dict(orient="records"):
        arms.append(
            ArmStats(
                arm_id=str(record["arm_id"]),
                name=str(record["name"]),
                clicks=int(record["clicks"]),
                conversions=int(record["conversions"]),
                cost=Decimal(str(record["cost"])),
                revenue=Decimal(str(record.get("revenue", 0))),
                platform=platform,
            )
        )
    return arms


def run_plan(
    factory: ProviderFactory,
    config: AppConfig,
    *,
    seed: int | None = _DEFAULT_SEED,
    n_samples: int = _DEFAULT_SAMPLES,
    kelly_fraction: float = 0.5,
) -> PlanResult:
    """Executa Modulul 2: dimensionare Kelly + alocare Thompson + atribuire Markov.

    Kelly foloseste avantajul contului (ROAS) ca sa stabileasca *plafonul zilnic
    absolut*; Thompson distribuie apoi acel plafon intre campanii/grupuri de
    anunturi/seturi de reclame — pe tot contul, indiferent de platforma.
    Bratele Google Ads, TikTok Ads si Meta Ads se combina intr-o singura lista
    inainte de Kelly/Thompson (un singur plafon, o singura alocare): asta e
    sensul unui bandit — bugetul curge spre bratul cel mai bun, nu spre
    platforma cea mai buna. Meta participa acum si aici, nu doar la lichiditate
    (``alignment/``) — foloseste aceleasi cinci seturi de reclame din
    ``providers.mock.meta``, vazute acum si prin ``clicks``/``revenue``. La
    fel, parcursurile de conversie de pe toate platformele se combina inainte
    de atribuirea Markov.
    Plafonul Kelly poate depasi ``budget.max_daily_spend``, dar niciodata
    ``HARD_CEILING``. Daca ``config.budget.target_cpa`` e setat, pragul minim
    per brat (``min_arm_daily_spend``) e ridicat automat cat sa incapa un
    verdict Gate B in orizontul implicit de evaluare - vezi
    ``decision.budget_strategy.recommend_arm_capacity`` (relevant la conturi cu
    buget mic, unde altfel bugetul s-ar dilua intre prea multe brate).

    Args:
        factory: Fabrica de furnizori (mock sau live).
        config: Configuratia aplicatiei (buget, praguri).
        seed: Seed pentru esantionarea Thompson (reproducibilitate CLI si teste).
        n_samples: Numarul de esantioane Monte Carlo per posterior.
        kelly_fraction: Fractia Kelly (``0.5`` = Half-Kelly; ``0`` dezactiveaza scalarea).

    Returns:
        Planul complet: dimensionare Kelly + alocare de buget + atribuire.
    """
    ads = factory.google_ads()
    tiktok_ads = factory.tiktok_ads()
    meta_ads = factory.meta()

    google_arms = _arms_from_performance(
        ads.campaign_performance(_CUSTOMER_PLACEHOLDER), platform="google_ads"
    )
    tiktok_arms = _arms_from_performance(
        tiktok_ads.campaign_performance(_ADVERTISER_PLACEHOLDER), platform="tiktok_ads"
    )
    meta_arms = _arms_from_performance(
        meta_ads.campaign_performance(_META_ACCOUNT_PLACEHOLDER), platform="meta_ads"
    )
    arms = google_arms + tiktok_arms + meta_arms

    kelly = size_daily_budget(
        arms,
        baseline_cap=config.budget.max_daily_spend,
        hard_ceiling=HARD_CEILING,
        kelly_fraction=kelly_fraction,
    )

    min_arm_daily_spend = config.budget.min_arm_daily_spend
    arm_capacity: ArmCapacityAdvice | None = None
    if config.budget.target_cpa is not None:
        arm_capacity = recommend_arm_capacity(kelly.sized_daily_cap, config.budget.target_cpa)
        min_arm_daily_spend = max(min_arm_daily_spend, arm_capacity.recommended_min_arm_daily_spend)

    allocator = ThompsonBudgetAllocator(min_arm_daily_spend=min_arm_daily_spend)
    budget_plan = allocator.allocate(
        arms,
        float(kelly.sized_daily_cap),
        n_samples=n_samples,
        seed=seed,
    )

    journeys = [
        Journey.from_tokens(path)
        for path in (
            *ads.conversion_paths(_CUSTOMER_PLACEHOLDER),
            *tiktok_ads.conversion_paths(_ADVERTISER_PLACEHOLDER),
            *meta_ads.conversion_paths(_META_ACCOUNT_PLACEHOLDER),
        )
    ]
    attribution = attribute(journeys)

    return PlanResult(
        kelly=kelly, budget_plan=budget_plan, attribution=attribution, arm_capacity=arm_capacity
    )


def render_plan(result: PlanResult, console: Console) -> None:
    """Afiseaza dimensionarea Kelly, planul de buget si atribuirea in consola."""
    _render_kelly(result, console)
    if result.arm_capacity is not None:
        render_arm_capacity(result.arm_capacity, console)
    _render_budget(result, console)
    _render_attribution(result, console)


def _render_kelly(result: PlanResult, console: Console) -> None:
    kelly = result.kelly
    console.print(
        f"\n[bold]Dimensionare Kelly (plafon zilnic absolut)[/bold]  "
        f"edge={kelly.edge}"
    )
    console.print(
        f"  ROAS cont {kelly.account_roas:.2f}  |  CVR neteda {kelly.smoothed_cvr:.4f}  "
        f"|  Half-Kelly f={kelly.kelly_fraction:+.3f}  |  x{kelly.multiplier:.2f}"
    )
    console.print(
        f"  plafon: baseline {kelly.baseline_cap} -> [bold]{kelly.sized_daily_cap}[/bold] "
        f"/ zi  (plafon absolut {kelly.hard_ceiling})"
    )
    console.print(f"  [dim]{kelly.rationale}[/dim]")


def render_arm_capacity(advice: ArmCapacityAdvice, console: Console) -> None:
    console.print(
        f"\n[bold]Capacitate per buget[/bold]  tier={advice.tier}  "
        f"(target_cpa {advice.target_cpa}, orizont {advice.target_evaluation_days:.0f}z)"
    )
    console.print(
        f"  maxim [bold]{advice.recommended_max_concurrent_arms}[/bold] variante active  |  "
        f"minim {advice.recommended_min_arm_daily_spend}/zi per brat"
    )
    console.print(f"  [dim]{advice.rationale}[/dim]")


def _render_budget(result: PlanResult, console: Console) -> None:
    plan = result.budget_plan
    console.print(
        f"\n[bold]Alocare buget - Thompson Sampling[/bold]  "
        f"(buget {plan.daily_budget} / zi, {plan.n_samples} esantioane, seed {plan.seed})"
    )
    table = Table()
    for name in ("campanie", "platforma", "P(cel mai bun)", "cota", "buget/zi", "nota"):
        table.add_column(name)
    for item in plan.allocations:
        table.add_row(
            item.name,
            item.platform,
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
