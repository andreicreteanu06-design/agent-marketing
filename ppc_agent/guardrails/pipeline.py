"""Construieste seturi de modificari propuse din iesirile Modulelor 1-3 si le reda."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from ppc_agent.alignment.models import AdSet, LiquidityPlan
from ppc_agent.decision.fatigue_models import AdPerformanceState, FatigueVerdict
from ppc_agent.decision.fatigue_monitor import evaluate_ad, explain_verdict
from ppc_agent.decision.models import ArmStats, BudgetPlan, KellySizing
from ppc_agent.guardrails.models import ChangeSet, ProposedChange
from ppc_agent.ingestion.models import NegativeKeywordSet

_MAX_NEGATIVES_IN_CHANGESET = 40
#: Cat poate urca sau cobori bugetul unui set Meta intr-o noapte. Un salt mare e o
#: "editare semnificativa" pentru Meta: reporneste faza de invatare, iar ROAS-ul
#: scade cateva zile. Planul Thompson ajunge la tinta in pasi, noapte de noapte.
MAX_BUDGET_STEP = Decimal("0.20")
_CENT = Decimal("0.01")
_PAUSE_VERDICTS: frozenset[FatigueVerdict] = frozenset(
    {"PAUSE_HARD", "PAUSE_PROVISIONAL", "PAUSE_REPLACE"}
)
#: Resursa si tipul obiectului pe care sta bugetul, pe platforma (in afara de Meta).
_BUDGET_RESOURCES = {
    "google_ads": ("campaign/", "campaign"),
    "tiktok_ads": ("tiktok_ad_group/", "ad_group"),
    "chatgpt_ads": ("chatgpt_campaign/", "campaign"),
}


def _step(now: Decimal, target: Decimal) -> Decimal:
    """``target``, dar cel mult ``MAX_BUDGET_STEP`` fata de bugetul de acum."""
    step = (now * MAX_BUDGET_STEP).quantize(_CENT)
    return min(now + step, max(now - step, target))


def build_proposed_changes(
    *,
    budget_plan: BudgetPlan,
    negatives: NegativeKeywordSet,
    liquidity: LiquidityPlan,
    kelly: KellySizing | None = None,
    ad_sets: Sequence[AdSet] | None = None,
    arms: Sequence[ArmStats] | None = None,
) -> list[ProposedChange]:
    """Traduce planurile Modulelor 1-3 in modificari propuse, inca neaplicate.

    - Buget (Modulul 2): un ``UPDATE`` per campanie/grup de anunturi/set de
      reclame cu buget, ``PAUSE`` pentru cele duse la 0. ``projected_daily_spend``
      poarta bugetul zilnic rezultat. Resursa se numeste dupa platforma
      bratului: Google Ads ramane ``campaign/{arm_id}``, TikTok Ads devine
      ``tiktok_ad_group/{arm_id}`` (``resource_type`` ``"ad_group"``), Meta Ads
      devine ``meta_ad_set/{arm_id}`` (``resource_type`` ``"ad_set"`` — distinct
      de ``ad_set_group/...`` folosit mai jos de consolidarile de lichiditate,
      diferentiat prin ``source_module``). Cand ``kelly`` este dat, rationamentul
      Half-Kelly se adauga la fiecare modificare de buget.
    - Cuvinte cheie negative (Modulul 1): ``CREATE``, fara impact pe cheltuiala.
    - Consolidari Meta (Modulul 3): ``UPDATE``, fara impact pe cheltuiala zilnica
      Google (bugetul Meta este guvernat separat).

    Args:
        budget_plan: Planul de alocare Thompson.
        negatives: Setul de cuvinte cheie negative.
        liquidity: Planul de lichiditate Meta.
        kelly: Dimensionarea Kelly a plafonului zilnic (optional).
        ad_sets: Seturile Meta citite din cont (``AlignmentResult.ad_sets``). Cand sunt
            date, bugetele Meta pleaca de la bugetul de acum: cel mult
            ``MAX_BUDGET_STEP`` pe noapte, niciunul pe un set aflat in invatare
            (``LEARNING``) sau cu bugetul pe campanie, iar un set "dus la 0" coboara
            treptat, nu se opreste. Un set cu invatarea limitata primeste pasi: lui
            bugetul ii poate aduce conversiile care ii lipsesc.
        arms: Bratele planului (``PlanResult.arms``). Pe Google, TikTok si ChatGPT,
            bugetul pleaca de la cel raportat de platforma, in aceiasi pasi ca la Meta
            (si acolo un salt mare reporneste invatarea algoritmului); un brat cu
            bugetul blocat (``ArmStats.budget_locked``: partajat, pe campanie, pe viata,
            in invatare) nu se atinge. Fara bugetul de acum, tinta Thompson ramane.

    Returns:
        Lista de :class:`ProposedChange`.
    """
    changes: list[ProposedChange] = []
    kelly_note = f" {kelly.rationale}" if kelly is not None else ""
    current = {ad_set.ad_set_id: ad_set for ad_set in ad_sets or ()}
    by_arm = {(arm.platform, arm.arm_id): arm for arm in arms or ()}

    for allocation in budget_plan.allocations:
        target = allocation.daily_budget
        before: dict[str, Any] = {}
        thompson = (
            allocation.note
            or f"Thompson Sampling: P(cel mai bun)={allocation.win_probability:.3f}"
        )
        if allocation.platform == "meta_ads":
            resource = f"meta_ad_set/{allocation.arm_id}"
            resource_type = "ad_set"
            if ad_sets is not None:
                ad_set = current.get(allocation.arm_id)
                if (
                    ad_set is None
                    or ad_set.learning_status == "LEARNING"
                    or ad_set.daily_budget is None
                ):
                    continue  # necunoscut, in invatare sau buget pe campanie: nu se atinge
                now = ad_set.daily_budget
                target = _step(now, target)
                if target == now:
                    continue
                before = {"daily_budget": str(now)}
                thompson += (
                    f" (tinta {allocation.daily_budget}, pas maxim "
                    f"{(now * MAX_BUDGET_STEP).quantize(_CENT)}/noapte)"
                )
        else:
            prefix, resource_type = _BUDGET_RESOURCES.get(
                allocation.platform, ("campaign/", "campaign")
            )
            resource = f"{prefix}{allocation.arm_id}"
            arm = by_arm.get((allocation.platform, allocation.arm_id))
            if arm is not None and arm.budget_locked:
                continue
            if arm is not None and arm.daily_budget is not None:
                now = arm.daily_budget
                target = _step(now, target)
                if target == now:
                    continue
                before = {"daily_budget": str(now)}
                thompson += (
                    f" (tinta {allocation.daily_budget}, pas maxim "
                    f"{(now * MAX_BUDGET_STEP).quantize(_CENT)}/noapte)"
                )
        changes.append(
            ProposedChange(
                op="PAUSE" if target == 0 else "UPDATE",
                resource=resource,
                resource_type=resource_type,
                before=before,
                after={"daily_budget": str(target)},
                projected_daily_spend=target,
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


#: Resursa unui anunt de oprit, pe platforma (monitorul de oboseala).
_AD_RESOURCES = {"meta": "meta_ad/", "tiktok": "tiktok_ad/"}


def build_fatigue_changes(
    ads: list[AdPerformanceState], current_time: datetime
) -> list[ProposedChange]:
    """Traduce verdictele monitorului de oboseala in modificari propuse ``PAUSE``.

    Doar verdictele care inseamna efectiv "opreste anuntul" produc o intrare
    (``PAUSE_HARD``/``PAUSE_PROVISIONAL``/``PAUSE_REPLACE``) - ``CONTINUE`` si
    ``HOLD_FOR_LAG`` inseamna "asteapta", nu "opreste", deci nu genereaza nimic.
    Toate cele trei se mapeaza pe ``op="PAUSE"`` (singura operatie relevanta la
    nivel de API de reclame); distinctia dintre ele (kill sigur vs. provizoriu
    vs. oboseala creativa) ramane in ``rationale``, pentru revizuirea umana.

    Args:
        ads: Stariile de performanta de evaluat.
        current_time: Momentul evaluarii, acelasi pentru toate anunturile.

    Returns:
        Lista de :class:`ProposedChange` (``op="PAUSE"``), gata de adaugat
        intr-un :class:`~ppc_agent.guardrails.approval_gate.ApprovalGate`
        existent - fluxul ``propose -> flush -> execute --confirm`` nu se
        modifica deloc.
    """
    changes: list[ProposedChange] = []
    for ad in ads:
        verdict = evaluate_ad(ad, current_time)
        if verdict not in _PAUSE_VERDICTS:
            continue
        changes.append(
            ProposedChange(
                op="PAUSE",
                # ``meta_ad/`` e numele pe care motorul de executie il aplica in Meta;
                # Google n-are executor pentru anunturi (cere si grupul) - de oprit manual.
                resource=_AD_RESOURCES.get(ad.platform, "ad/") + ad.ad_id,
                resource_type="ad",
                before={"status": ad.status},
                after={"status": "paused", "verdict": verdict, "platform": ad.platform},
                rationale=f"[{verdict}] {explain_verdict(ad, verdict, current_time)}",
                source_module="fatigue_monitor",
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


def render_fatigue_evaluations(
    ads: list[AdPerformanceState], current_time: datetime, console: Console
) -> None:
    """Afiseaza verdictul monitorului de oboseala pentru fiecare anunt evaluat."""
    table = Table(title="Monitor de oboseala")
    for name in ("anunt", "platforma", "status", "verdict", "motiv"):
        table.add_column(name)
    for ad in ads:
        verdict = evaluate_ad(ad, current_time)
        style = "red" if verdict in _PAUSE_VERDICTS else None
        table.add_row(
            ad.ad_id,
            ad.platform,
            ad.status,
            verdict,
            explain_verdict(ad, verdict, current_time),
            style=style,
        )
    console.print(table)


def latest_changeset_path(directory: Path) -> Path | None:
    """Cea mai recenta cale ``proposed_changes_*.json`` din ``directory``, sau ``None``."""
    candidates = sorted(directory.glob("proposed_changes_*.json"))
    return candidates[-1] if candidates else None
