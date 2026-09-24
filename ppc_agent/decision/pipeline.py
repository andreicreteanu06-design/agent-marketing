"""Orchestrarea Modulului 2 si redarea rezultatului in consola."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

import pandas as pd
from rich.console import Console
from rich.table import Table

from ppc_agent.config import AppConfig
from ppc_agent.decision.attribution import Journey, attribute
from ppc_agent.decision.budget import ThompsonBudgetAllocator
from ppc_agent.decision.budget_strategy import recommend_arm_capacity
from ppc_agent.decision.forecasting import Forecaster, apply_forecast
from ppc_agent.decision.kelly_sizing import size_daily_budget
from ppc_agent.decision.models import ArmCapacityAdvice, ArmStats, DailyArmMetric, PlanResult
from ppc_agent.guardrails.spend_limiter import HARD_CEILING
from ppc_agent.providers.factory import ProviderFactory

_CUSTOMER_PLACEHOLDER = "mock-customer"
_ADVERTISER_PLACEHOLDER = "mock-advertiser"
_META_ACCOUNT_PLACEHOLDER = "mock-account"
_DEFAULT_SEED = 20260101
_DEFAULT_SAMPLES = 20_000
_DEFAULT_HISTORY_DAYS = 30


def resolve_account_ids(config: AppConfig) -> tuple[str, str, str]:
    """(customer_id, advertiser_id, ad_account_id), cu fallback pe placeholder-ele mock.

    In mod live, ID-ul real de cont vine din configuratie; placeholder-ul e
    folosit doar cand campul e gol (implicit - asta pastreaza comportamentul
    mock neschimbat pentru toate testele existente).
    """
    customer_id = config.settings.google_ads_customer_id or _CUSTOMER_PLACEHOLDER
    advertiser_id = config.settings.tiktok_advertiser_id or _ADVERTISER_PLACEHOLDER
    ad_account_id = config.settings.meta_ad_account_id or _META_ACCOUNT_PLACEHOLDER
    return customer_id, advertiser_id, ad_account_id


@runtime_checkable
class SupportsDailyPerformance(Protocol):
    """Capacitate OPTIONALA: raportare zi-cu-zi, pentru forecasting (``--forecast`` in CLI).

    Niciun furnizor (mock sau live) nu o implementeaza inca - e un contract
    pregatit pentru cand se adauga ingestia zilnica reala (Google Ads GAQL cu
    ``segments.date``, Meta Insights API cu ``time_increment=1``, TikTok
    Reporting API cu ``stat_time_day``) - lucru separat, netratat aici.
    Deliberat NEIMPLEMENTAT de providerii mock: nu fabricam un trend zilnic
    dintr-un agregat static caruia nu i se cunoaste distributia reala.

    ``isinstance(provider, SupportsDailyPerformance)`` verifica la RUNTIME daca
    un anume furnizor o are, fara sa modifice ABC-urile din ``providers/base.py``
    (niciun furnizor existent, mock sau live, nu se strica).
    """

    def daily_campaign_performance(self, account_id: str, *, days: int) -> pd.DataFrame:
        """Performanta pe zile: aceleasi coloane ca ``campaign_performance()``, plus ``date``."""
        ...


def collect_daily_histories(
    providers_and_ids: list[tuple[object, str]], *, days: int = _DEFAULT_HISTORY_DAYS
) -> dict[str, list[DailyArmMetric]]:
    """Aduna istoricul zilnic de la providerii din ``providers_and_ids`` care implementeaza
    :class:`SupportsDailyPerformance`; ignora restul (fallback sigur - vezi docstring-ul ei).

    Intoarce ``{}`` cand niciun furnizor din lista nu o implementeaza - identic
    cu "fara forecasting" pentru ``run_plan(histories=...)``.
    """
    histories: dict[str, list[DailyArmMetric]] = {}
    for provider, account_id in providers_and_ids:
        if not isinstance(provider, SupportsDailyPerformance):
            continue
        frame = provider.daily_campaign_performance(account_id, days=days)
        for arm_id, group in frame.groupby("arm_id"):
            histories[str(arm_id)] = [
                DailyArmMetric(
                    date=record["date"],
                    clicks=int(record["clicks"]),
                    conversions=int(record["conversions"]),
                    cost=Decimal(str(record["cost"])),
                    revenue=Decimal(str(record.get("revenue", 0))),
                )
                for record in group.to_dict(orient="records")
            ]
    return histories


def arms_from_performance(frame: pd.DataFrame, *, platform: str = "google_ads") -> list[ArmStats]:
    """Tabelul ``campaign_performance()`` al unui furnizor, ca brate pentru Kelly/Thompson.

    Public fiindca il foloseste si brief-ul de lansare (``services/launch_brief.py``):
    aceeasi conversie a banilor in ``Decimal``, nu o a doua.
    """
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
    forecaster: Forecaster | None = None,
    histories: dict[str, list[DailyArmMetric]] | None = None,
    forecast_horizon_days: int = 14,
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

    ``forecaster``/``histories`` sunt OPTIONALE si NEactivate implicit -
    ``forecaster=None`` (implicit) pastreaza comportamentul exact de dinainte
    (Kelly/Thompson vad direct agregatele istorice ``ads.campaign_performance()``).
    Cand ambele sunt date, bratele cu istoric in ``histories`` (cheie ``arm_id``)
    intra in Kelly/Thompson ca ArmStats PROIECTATE pe urmatoarele
    ``forecast_horizon_days`` zile (vezi ``forecasting.apply_forecast``), in loc
    de agregatul brut - deciziile devin orientate spre unde se indreapta
    performanta, nu doar unde a fost. ``kelly_sizing.py``/``budget.py`` raman
    complet neschimbate: primesc un ArmStats ca oricare altul.

    Args:
        factory: Fabrica de furnizori (mock sau live).
        config: Configuratia aplicatiei (buget, praguri).
        seed: Seed pentru esantionarea Thompson (reproducibilitate CLI si teste).
        n_samples: Numarul de esantioane Monte Carlo per posterior.
        kelly_fraction: Fractia Kelly (``0.5`` = Half-Kelly; ``0`` dezactiveaza scalarea).
        forecaster: Cand e dat (impreuna cu ``histories``), proiecteaza bratele
            inainte de Kelly/Thompson - vezi ``forecasting.py``.
        histories: Istoricul zilnic per brat (cheie ``arm_id``), pentru ``forecaster``.
        forecast_horizon_days: Orizontul de proiectie (zile), cand ``forecaster`` e dat.

    Returns:
        Planul complet: dimensionare Kelly + alocare de buget + atribuire.
    """
    ads = factory.google_ads()
    tiktok_ads = factory.tiktok_ads()
    meta_ads = factory.meta()
    customer_id, advertiser_id, ad_account_id = resolve_account_ids(config)

    google_arms = arms_from_performance(
        ads.campaign_performance(customer_id), platform="google_ads"
    )
    tiktok_arms = arms_from_performance(
        tiktok_ads.campaign_performance(advertiser_id), platform="tiktok_ads"
    )
    meta_arms = arms_from_performance(
        meta_ads.campaign_performance(ad_account_id), platform="meta_ads"
    )
    arms = google_arms + tiktok_arms + meta_arms
    if forecaster is not None and histories:
        arms = apply_forecast(arms, histories, forecaster, horizon_days=forecast_horizon_days)

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
            *ads.conversion_paths(customer_id),
            *tiktok_ads.conversion_paths(advertiser_id),
            *meta_ads.conversion_paths(ad_account_id),
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
