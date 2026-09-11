"""Construieste seturi de modificari propuse din iesirile Modulelor 1-3 si le reda."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ppc_agent.alignment.models import LiquidityPlan
from ppc_agent.decision.models import BudgetPlan, KellySizing
from ppc_agent.guardrails.models import ChangeSet, ProposedChange
from ppc_agent.ingestion.models import NegativeKeywordSet

_MAX_NEGATIVES_IN_CHANGESET = 40


def build_proposed_changes(
    *,
    budget_plan: BudgetPlan,
    negatives: NegativeKeywordSet,
    liquidity: LiquidityPlan,
    kelly: KellySizing | None = None,
) -> list[ProposedChange]:
    """Traduce planurile Modulelor 1-3 in modificari propuse, inca neaplicate.

    - Buget (Modulul 2): un ``UPDATE`` per campanie/grup de anunturi cu buget,
      ``PAUSE`` pentru cele duse la 0. ``projected_daily_spend`` poarta bugetul
      zilnic rezultat. Resursa se numeste dupa platforma bratului: Google Ads
      ramane ``campaign/{arm_id}``, TikTok Ads devine ``tiktok_ad_group/{arm_id}``
      (``resource_type`` ``"campaign"`` vs. ``"ad_group"``). Cand ``kelly`` este
      dat, rationamentul Half-Kelly se adauga la fiecare modificare de buget.
    - Cuvinte cheie negative (Modulul 1): ``CREATE``, fara impact pe cheltuiala.
    - Consolidari Meta (Modulul 3): ``UPDATE``, fara impact pe cheltuiala zilnica
      Google (bugetul Meta este guvernat separat).

    Args:
        budget_plan: Planul de alocare Thompson.
        negatives: Setul de cuvinte cheie negative.
        liquidity: Planul de lichiditate Meta.
        kelly: Dimensionarea Kelly a plafonului zilnic (optional).

    Returns:
        Lista de :class:`ProposedChange`.
    """
    changes: list[ProposedChange] = []
    kelly_note = f" {kelly.rationale}" if kelly is not None else ""

    for allocation in budget_plan.allocations:
        zeroed = allocation.daily_budget == 0
        thompson = (
            allocation.note
            or f"Thompson Sampling: P(cel mai bun)={allocation.win_probability:.3f}"
        )
        if allocation.platform == "tiktok_ads":
            resource = f"tiktok_ad_group/{allocation.arm_id}"
            resource_type = "ad_group"
        else:
            resource = f"campaign/{allocation.arm_id}"
            resource_type = "campaign"
        changes.append(
            ProposedChange(
                op="PAUSE" if zeroed else "UPDATE",
                resource=resource,
                resource_type=resource_type,
                before={},
                after={"daily_budget": str(allocation.daily_budget)},
                projected_daily_spend=allocation.daily_budget,
                rationale=f"{thompson}.{kelly_note}",
                source_module="budget",
            )
        )

    for negative in negatives.items[:_MAX_NEGATIVES_IN_CHANGESET]:
        changes.append(
            ProposedChange(
                op="CREATE",
                resource=f"negative_keyword/{negative.term}",
                resource_type="negative_keyword",
                after={"term": negative.term, "match_type": negative.match_type},
                projected_daily_spend=Decimal("0"),
                rationale=f"{negative.reason_code}"
                + (f" ({negative.matched_token})" if negative.matched_token else ""),
                source_module="negatives",
            )
        )

    for merge in liquidity.merges:
        if len(merge.source_ids) < 2:
            continue
        changes.append(
            ProposedChange(
                op="UPDATE",
                resource=f"ad_set_group/{merge.merged_id}",
                resource_type="ad_set",
                after={
                    "source_ids": ", ".join(merge.source_ids),
                    "projected_weekly_conversions": merge.projected_weekly_conversions,
                },
                projected_daily_spend=Decimal("0"),
                rationale=(
                    "consolidare pentru lichiditate algoritmica "
                    f"(prag {liquidity.target_weekly_conversions} conversii/saptamana)"
                ),
                source_module="meta_liquidity",
            )
        )

    return changes


def render_changeset(changeset: ChangeSet, path: Path, console: Console) -> None:
    """Afiseaza un rezumat al unui changeset in consola."""
    console.print(
        f"\n[bold]Set de modificari propuse[/bold]  {path.name}\n"
        f"  cont: {changeset.account}\n"
        f"  cheltuiala zilnica propusa: {changeset.total_projected_daily_spend} "
        f"(limita {changeset.spend_limit}, plafon {changeset.hard_ceiling})\n"
        f"  modificari pe modul: {changeset.by_module()}"
    )
    table = Table()
    for name in ("op", "resursa", "cheltuiala/zi", "motiv"):
        table.add_column(name)
    for change in changeset.changes[:20]:
        table.add_row(
            change.op,
            change.resource,
            f"{change.projected_daily_spend}",
            change.rationale,
        )
    console.print(table)
    if len(changeset.changes) > 20:
        console.print(f"  ... si inca {len(changeset.changes) - 20} modificari")


def latest_changeset_path(directory: Path) -> Path | None:
    """Cea mai recenta cale ``proposed_changes_*.json`` din ``directory``, sau ``None``."""
    candidates = sorted(directory.glob("proposed_changes_*.json"))
    return candidates[-1] if candidates else None
