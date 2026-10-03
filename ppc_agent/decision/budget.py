"""Alocarea de buget prin Thompson Sampling (bandit bayesian, posteriori Gamma-Poisson).

Fara reguli euristice: fiecare brat primeste buget proportional cu probabilitatea
sa de a aduce cea mai mare valoare pe leu cheltuit - conversii pe leu (posterior
Gamma) inmultite cu valoarea unei conversii. Nu rata de conversie pe click: un brat
cu 5% conversie la click de 10 lei (CPA 200) e mai prost decat unul cu 3% la 1 leu
(CPA 33), desi ar castiga la CVR.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import torch

from ppc_agent.decision.models import ArmStats, BudgetAllocation, BudgetPlan
from ppc_agent.errors import BudgetAllocationError

_CENT = Decimal("0.01")


def _to_cents(value: float) -> Decimal:
    """Rotunjeste o valoare monetara la doua zecimale (jumatate in sus)."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _sum_decimals(values: list[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


class ThompsonBudgetAllocator:
    """Aloca bugetul zilnic intre brate proportional cu sansa de a fi optim.

    Math: conversiile unui brat sunt Poisson in cost, cu ``lambda`` conversii pe leu.
    Priorul e ``prior_conversions`` pseudo-conversii la CPA-ul mediu al contului, deci
    posteriorul e ``Gamma(prior + conversii, prior * CPA_cont + cost)``. Fiecare
    esantion ``lambda`` se inmulteste cu valoarea unei conversii a bratului (venit /
    conversii, tras spre media contului cu aceeasi pseudo-conversie; 1 cand nimeni nu
    are venit - atunci se compara doar CPA-urile). Cota bruta a unui brat este fractia
    de esantioane in care el aduce cea mai multa valoare pe leu (probabilitatea de
    castig). Cotele se taie la ``[min_share, max_share]`` si se renormalizeaza.
    """

    def __init__(
        self,
        *,
        prior_conversions: float = 1.0,
        min_arm_daily_spend: Decimal = Decimal("0"),
    ) -> None:
        """Configureaza priorul si pragul minim absolut per brat.

        Args:
            prior_conversions: Cate pseudo-conversii, la media contului, primeste
                fiecare brat - un brat nou porneste de la media, nu de la zero.
            min_arm_daily_spend: Buget zilnic minim sub care un brat este
                dezactivat (``0`` = fara prag).
        """
        if prior_conversions <= 0:
            raise BudgetAllocationError("priorul trebuie sa fie strict pozitiv")
        self._prior = prior_conversions
        self._floor = min_arm_daily_spend

    def _win_probabilities(
        self, arms: list[ArmStats], n_samples: int, seed: int | None
    ) -> list[float]:
        """Probabilitatea fiecarui brat de a aduce cea mai multa valoare pe leu."""
        cost = float(sum((arm.cost for arm in arms), Decimal("0")))
        conversions = sum(arm.conversions for arm in arms)
        revenue = float(sum((arm.revenue for arm in arms), Decimal("0")))
        account_cpa = max(cost, 1.0) / max(conversions, 1)
        account_value = revenue / conversions if conversions and revenue > 0 else 1.0
        shapes = [self._prior + arm.conversions for arm in arms]
        rates = [self._prior * account_cpa + float(arm.cost) for arm in arms]
        values = [
            (float(arm.revenue) + self._prior * account_value) / (arm.conversions + self._prior)
            if revenue > 0
            else 1.0
            for arm in arms
        ]

        rng_state = torch.random.get_rng_state()
        try:
            if seed is not None:
                torch.manual_seed(seed)
            shape_t = torch.tensor(shapes, dtype=torch.double)
            rate_t = torch.tensor(rates, dtype=torch.double)
            per_leu = torch.distributions.Gamma(shape_t, rate_t).sample((n_samples,))
            samples = per_leu * torch.tensor(values, dtype=torch.double)
            winners = torch.argmax(samples, dim=1)
            counts = torch.bincount(winners, minlength=len(arms)).to(torch.double)
            probs = (counts / float(n_samples)).tolist()
        finally:
            torch.random.set_rng_state(rng_state)

        return [float(value) for value in probs]

    def allocate(
        self,
        arms: list[ArmStats],
        daily_budget: float,
        *,
        n_samples: int = 10_000,
        min_share: float = 0.05,
        max_share: float = 0.6,
        seed: int | None = None,
    ) -> BudgetPlan:
        """Distribuie ``daily_budget`` intre ``arms``.

        Args:
            arms: Brate cu performanta istorica.
            daily_budget: Bugetul zilnic total de impartit.
            n_samples: Numarul de esantioane Monte Carlo per posterior.
            min_share: Cota minima per brat inainte de renormalizare.
            max_share: Cota maxima per brat inainte de renormalizare.
            seed: Seed pentru reproducibilitate (fixeaza si restaureaza RNG-ul torch).

        Returns:
            Planul de buget, cu buget si probabilitate de castig per brat.

        Raises:
            BudgetAllocationError: Daca lista de brate e goala, bugetul e negativ
                sau intervalul de cote e invalid.
        """
        if not arms:
            raise BudgetAllocationError("este nevoie de cel putin un brat")
        if daily_budget < 0:
            raise BudgetAllocationError("bugetul zilnic nu poate fi negativ")
        if not 0.0 <= min_share <= max_share <= 1.0:
            raise BudgetAllocationError("trebuie 0 <= min_share <= max_share <= 1")

        win_probs = self._win_probabilities(arms, n_samples, seed)
        shares = _clip_and_normalise(win_probs, min_share, max_share)
        budgets, notes = _apply_floor(
            [share * daily_budget for share in shares],
            win_probs,
            floor=float(self._floor),
            daily_budget=daily_budget,
        )
        money = _quantise_to_budget(budgets, daily_budget)
        total = _sum_decimals(money)

        allocations = [
            BudgetAllocation(
                arm_id=arm.arm_id,
                name=arm.name,
                platform=arm.platform,
                win_probability=round(win_probs[index], 6),
                final_share=float(money[index] / total) if total > 0 else 0.0,
                daily_budget=money[index],
                note=notes[index],
            )
            for index, arm in enumerate(arms)
        ]
        return BudgetPlan(
            daily_budget=_to_cents(daily_budget),
            total_allocated=total,
            n_samples=n_samples,
            seed=seed,
            allocations=allocations,
        )


def _clip_and_normalise(values: list[float], low: float, high: float) -> list[float]:
    """Cote in ``[low, high]`` care insumeaza 1, prin umplere iterativa (water-filling).

    Math: se porneste de la cotele normalizate; la fiecare pas cotele se taie la
    ``[low, high]``, iar surplusul sau deficitul fata de 1 se redistribuie
    proportional cu spatiul liber al cotelor neblocate, pana la convergenta. Astfel
    un brat dominant se opreste exact la ``high``, spre deosebire de "taie apoi
    renormalizeaza" care l-ar impinge peste ``high``.
    """
    n = len(values)
    total = sum(values)
    shares = [value / total for value in values] if total > 0 else [1.0 / n] * n

    for _ in range(2 * n + 2):
        clipped = [min(high, max(low, share)) for share in shares]
        gap = 1.0 - sum(clipped)
        if abs(gap) < 1e-12:
            return clipped
        if gap < 0:
            adjustable = [i for i in range(n) if clipped[i] > low + 1e-15]
            room = sum(clipped[i] - low for i in adjustable) or 1.0
        else:
            adjustable = [i for i in range(n) if clipped[i] < high - 1e-15]
            room = sum(high - clipped[i] for i in adjustable) or 1.0
        if not adjustable:
            return clipped
        shares = list(clipped)
        for i in adjustable:
            headroom = (clipped[i] - low) if gap < 0 else (high - clipped[i])
            shares[i] += gap * headroom / room
    return [min(high, max(low, share)) for share in shares]


def _apply_floor(
    budgets: list[float],
    win_probs: list[float],
    *,
    floor: float,
    daily_budget: float,
) -> tuple[list[float], list[str | None]]:
    """Aplica pragul minim absolut per brat.

    Math: se pot finanta cel mult ``k = floor(daily_budget / floor)`` brate. Se
    pastreaza primele ``k`` dupa probabilitatea de castig (apoi dupa buget), restul
    trec pe ``0`` cu nota. Bugetele pastrate se renormalizeaza la ``daily_budget``,
    apoi bratele ramase sub prag sunt ridicate la ``floor`` cu diferenta luata
    proportional din bratele aflate deasupra pragului. Daca ``daily_budget < floor``
    se pastreaza un singur brat, marcat corespunzator.
    """
    count = len(budgets)
    notes_map: dict[int, str] = {}
    if floor <= 0 or daily_budget <= 0:
        return budgets, [notes_map.get(i) for i in range(count)]

    max_keep = max(1, int(daily_budget // floor))
    ranked = sorted(
        range(count), key=lambda i: (win_probs[i], budgets[i]), reverse=True
    )
    kept = sorted(ranked[:max_keep])
    for i in range(count):
        if i not in kept:
            notes_map[i] = f"sub pragul minim de {floor:.2f}, dezactivat"

    kept_weight = sum(budgets[i] for i in kept) or 1.0
    result = [0.0] * count
    for i in kept:
        result[i] = daily_budget * budgets[i] / kept_weight

    if len(kept) == 1:
        if result[kept[0]] < floor - 1e-9:
            notes_map[kept[0]] = f"buget zilnic sub pragul minim de {floor:.2f}"
        return result, [notes_map.get(i) for i in range(count)]

    for _ in range(len(kept)):
        deficit = {i: floor - result[i] for i in kept if result[i] < floor - 1e-9}
        if not deficit:
            break
        needed = sum(deficit.values())
        donors = [i for i in kept if result[i] > floor + 1e-9]
        donor_room = sum(result[i] - floor for i in donors) or 1.0
        for i in donors:
            result[i] -= needed * (result[i] - floor) / donor_room
        for i in deficit:
            result[i] = floor

    return result, [notes_map.get(i) for i in range(count)]


def _quantise_to_budget(budgets: list[float], daily_budget: float) -> list[Decimal]:
    """Rotunjeste la bani si pune restul de rotunjire pe cea mai mare alocare."""
    money = [_to_cents(value) for value in budgets]
    drift = _to_cents(daily_budget) - _sum_decimals(money)
    if drift != 0:
        largest = max(range(len(money)), key=lambda i: money[i])
        money[largest] += drift
    return money
