"""Lichiditate algoritmica Meta: consolidarea seturilor de reclame micro-segmentate.

Obiectiv: fiecare set de reclame rezultat sa proiecteze cel putin
``target_weekly_conversions`` evenimente/saptamana, ca sa iasa rapid din faza de
invatare. Fara aleator: gruparea se face pe suprapunerea de audienta (Jaccard).
"""

from __future__ import annotations

from ppc_agent.alignment.models import AdSet, AdSetMerge, LiquidityPlan
from ppc_agent.texttools import tokenize

_AUDIENCE_OVERLAP_THRESHOLD = 0.30
_LEARNING_WINDOW_DAYS = 7.0
_LEARNING_EVENTS = 50.0
_MAX_LEARNING_DAYS = 14.0


def _audience_tokens(ad_set: AdSet) -> set[str]:
    return set(tokenize(ad_set.audience_def))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _cluster_by_audience(ad_sets: list[AdSet]) -> list[list[AdSet]]:
    """Grupeaza seturile prin suprapunere de audienta tranzitiva (Jaccard >= prag)."""
    tokens = [_audience_tokens(ad_set) for ad_set in ad_sets]
    parent = list(range(len(ad_sets)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for i in range(len(ad_sets)):
        for j in range(i + 1, len(ad_sets)):
            if _jaccard(tokens[i], tokens[j]) >= _AUDIENCE_OVERLAP_THRESHOLD:
                parent[find(i)] = find(j)

    groups: dict[int, list[AdSet]] = {}
    for index, ad_set in enumerate(ad_sets):
        groups.setdefault(find(index), []).append(ad_set)
    return list(groups.values())


def _learning_exit_days(projected_weekly: float, target: float) -> float | None:
    """Zile estimate pana la iesirea din faza de invatare, sau ``None`` daca nu iese.

    Math: Meta cere ~``50`` evenimente de optimizare in ~``7`` zile. La un ritm de
    ``projected_weekly / 7`` pe zi, sunt necesare ``50 / ritm`` zile, plafonat la 14.
    Daca ritmul nu atinge pragul, faza de invatare nu se incheie -> ``None``.
    """
    if projected_weekly < target:
        return None
    daily_rate = projected_weekly / _LEARNING_WINDOW_DAYS
    if daily_rate <= 0.0:
        return None
    return round(min(_MAX_LEARNING_DAYS, _LEARNING_EVENTS / daily_rate), 1)


def consolidation_plan(
    ad_sets: list[AdSet], target_weekly_conversions: int = 50
) -> LiquidityPlan:
    """Propune consolidari astfel incat fiecare set rezultat sa atinga pragul.

    Pasi:

    1. Seturile deja sanatoase (``weekly_conversions >= prag`` si nu in invatare)
       raman neatinse.
    2. Restul se grupeaza pe suprapunere de audienta.
    3. Grupurile a caror proiectie (suma conversiilor) nu atinge pragul sunt
       fuzionate intre ele (targeting mai larg) pana la atingerea pragului sau
       pana cand ramane un singur grup.
    4. Fiecare fuziune primeste o estimare de iesire din invatare si avertismente.

    Args:
        ad_sets: Seturile de reclame ale contului.
        target_weekly_conversions: Pragul de evenimente/saptamana.

    Returns:
        Planul de lichiditate: fuziuni, seturi neatinse, recomandare CBO, avertismente.
    """
    target = float(target_weekly_conversions)
    healthy = [
        ad_set
        for ad_set in ad_sets
        if ad_set.weekly_conversions >= target and not ad_set.learning_phase
    ]
    healthy_ids = {ad_set.ad_set_id for ad_set in healthy}
    weak = [ad_set for ad_set in ad_sets if ad_set.ad_set_id not in healthy_ids]

    plan = LiquidityPlan(
        target_weekly_conversions=target_weekly_conversions,
        untouched_ids=[ad_set.ad_set_id for ad_set in healthy],
    )
    if not weak:
        return plan

    clusters = _cluster_by_audience(weak)
    clusters.sort(key=lambda group: sum(a.weekly_conversions for a in group), reverse=True)

    # Fuzioneaza grupuri sub-prag pana cand fiecare grup ramas atinge pragul.
    merged_groups: list[list[AdSet]] = []
    pending: list[AdSet] = []
    for cluster in clusters:
        pending.extend(cluster)
        if sum(a.weekly_conversions for a in pending) >= target:
            merged_groups.append(pending)
            pending = []
    if pending:
        if merged_groups:
            merged_groups[-1].extend(pending)
        else:
            merged_groups.append(pending)

    for index, group in enumerate(merged_groups, start=1):
        projected = round(sum(a.weekly_conversions for a in group), 2)
        clears = projected >= target
        warnings: list[str] = []
        if not clears:
            warnings.append(
                f"proiectie {projected:.0f} < prag {target:.0f}/saptamana, "
                "chiar si dupa fuziune - largeste audienta sau creste bugetul"
            )
        if len(group) == 1:
            warnings.append("un singur set in grup - nu exista micro-segmentare de rezolvat")
        plan.merges.append(
            AdSetMerge(
                merged_id=f"merged_{index}",
                source_ids=[a.ad_set_id for a in group],
                projected_weekly_conversions=projected,
                clears_threshold=clears,
                learning_exit_days=_learning_exit_days(projected, target),
                warnings=warnings,
            )
        )

    real_merges = [merge for merge in plan.merges if len(merge.source_ids) > 1]
    plan.recommend_cbo = bool(real_merges)
    if real_merges:
        plan.warnings.append(
            "activeaza Campaign Budget Optimization pe campania consolidata, cu "
            "buget minim per set de reclame ca sa nu fie infometate variantele noi"
        )
    return plan
