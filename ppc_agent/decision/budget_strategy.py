"""Consilier de capacitate per buget, pentru conturi cu buget zilnic mic.

Fara reguli euristice noi: totul se deriva din acelasi multiplicator pe care
Gate B (Kill Switch, vezi :mod:`ppc_agent.decision.fatigue_monitor`) il
foloseste deja pentru a declara un anunt nou pierzator. Ideea: un brat caruia
i se aloca mai putin decat pragul necesar pentru a atinge acel multiplicator
intr-un orizont de evaluare rezonabil nu va ajunge NICIODATA la un verdict -
ramane etern nediagnosticat, iar bugetul se scurge fara nicio decizie. La
conturi cu 10-25 lei/zi, asta se intampla usor daca bugetul e impartit intre
prea multe variante de creatie simultan.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ppc_agent.decision.fatigue_monitor import new_ad_hard_kill_spend_multiplier
from ppc_agent.decision.models import ArmCapacityAdvice, ArmCapacityTier
from ppc_agent.errors import BudgetAllocationError

_CENT = Decimal("0.01")
DEFAULT_EVALUATION_DAYS = 7.0
"""Orizont implicit de evaluare - o "saptamana de invatare", convenția uzuala
Google/Meta pentru iesirea din faza de invatare a unei campanii noi."""


def _tier_for(max_arms: int) -> ArmCapacityTier:
    if max_arms <= 1:
        return "micro"
    if max_arms <= 4:
        return "standard"
    return "scale"


def recommend_arm_capacity(
    daily_budget: Decimal | float,
    target_cpa: Decimal | float,
    *,
    target_evaluation_days: float = DEFAULT_EVALUATION_DAYS,
) -> ArmCapacityAdvice:
    """Recomanda pragul minim de cheltuiala per brat si numarul maxim de variante active.

    Math: Gate B (``PAUSE_HARD``) declara un anunt nou pierzator dupa ce
    cheltuiala lui ajunge la ``multiplicator x target_cpa`` (vezi
    ``fatigue_monitor.new_ad_hard_kill_spend_multiplier``). Un brat care nu
    poate atinge acel prag in ``target_evaluation_days`` zile ramane etern
    nediagnosticat - de-asta pragul minim per brat se deriva de aici
    (``multiplicator x target_cpa / target_evaluation_days``), nu dintr-un
    numar arbitrar de configurare. Numarul maxim de brate active e cate astfel
    de praguri incap in ``daily_budget``.

    Args:
        daily_budget: Bugetul zilnic total al contului (dupa dimensionarea Kelly).
        target_cpa: Costul tinta per achizitie/lead al contului.
        target_evaluation_days: In cate zile se doreste un verdict Gate B
            pentru un brat nou (implicit 7).

    Returns:
        Recomandarea de capacitate, cu motivul in ``rationale``.

    Raises:
        BudgetAllocationError: Daca bugetul, ``target_cpa`` sau orizontul de
            evaluare nu sunt strict pozitive.
    """
    budget = Decimal(str(daily_budget))
    cpa = Decimal(str(target_cpa))
    if budget <= 0 or cpa <= 0 or target_evaluation_days <= 0:
        raise BudgetAllocationError(
            "bugetul zilnic, target_cpa si orizontul de evaluare trebuie sa fie strict pozitive"
        )

    multiplier = Decimal(str(new_ad_hard_kill_spend_multiplier()))
    min_arm_spend = (multiplier * cpa / Decimal(str(target_evaluation_days))).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    max_arms = max(1, int(budget // min_arm_spend)) if min_arm_spend > 0 else 1
    tier = _tier_for(max_arms)

    if max_arms == 1:
        rationale = (
            f"buget {budget}/zi sustine sigur o singura varianta activa la target_cpa "
            f"{cpa}: sub {min_arm_spend}/zi per brat, verdictul Gate B (PAUSE_HARD, "
            f"{multiplier:.1f}x target_cpa) ar dura peste {target_evaluation_days:.0f} zile"
        )
    else:
        rationale = (
            f"buget {budget}/zi sustine pana la {max_arms} variante active la target_cpa "
            f"{cpa} (minim {min_arm_spend}/zi per brat), fiecare ajungand la un verdict "
            f"Gate B in cel mult {target_evaluation_days:.0f} zile"
        )

    return ArmCapacityAdvice(
        daily_budget=budget,
        target_cpa=cpa,
        target_evaluation_days=target_evaluation_days,
        recommended_min_arm_daily_spend=min_arm_spend,
        recommended_max_concurrent_arms=max_arms,
        tier=tier,
        rationale=rationale,
    )
