"""Criteriul lui Kelly (fractional / Half-Kelly) pentru dimensionarea plafonului zilnic.

Thompson Sampling decide *distributia* bugetului intre campanii (cote relative).
Kelly decide *marimea absoluta* a plafonului zilnic, in functie de avantajul
matematic al contului (EV / ROAS):

- avantaj pozitiv  -> se poate propune un plafon peste ``budget.max_daily_spend``,
  scalat catre ``HARD_CEILING`` (dar niciodata peste)
- avantaj nul       -> plafonul se mentine la ``budget.max_daily_spend``
- avantaj negativ  -> plafonul se reduce, pentru a pastra capitalul

``HARD_CEILING`` din :class:`~ppc_agent.guardrails.spend_limiter.AbsoluteSpendLimiter`
ramane limita absoluta, inviolabila. Nimic nu se cheltuie fara aprobare umana.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ppc_agent.decision.models import ArmStats, EdgeLabel, KellySizing

_CENT = Decimal("0.01")
_MIN_CAP = Decimal("1.00")
_MULTIPLIER_FLOOR = 0.5
_MULTIPLIER_CEIL = 2.0
_EPS = 1e-9


def calculate_kelly_fraction(
    win_prob: float, roas_odds: float, fraction: float = 0.5
) -> float:
    """Fractia Kelly (implicit Half-Kelly).

    Math: Kelly complet este ``f* = (p*b - q) / b``, unde ``p = win_prob``,
    ``q = 1 - p`` si ``b = roas_odds``. Rezultatul se inmulteste cu ``fraction``
    (``0.5`` = Half-Kelly) pentru a limita volatilitatea si se taie la ``[-1, 1]``.

    Daca ``b <= 0`` nu exista avantaj: se intoarce ``fraction * b`` — ``0`` cand
    ``b == 0`` (mentine), negativ cand ``b < 0`` (semnal de reducere).

    Args:
        win_prob: Probabilitatea unui rezultat favorabil, in ``[0, 1]``.
        roas_odds: Castigul fractional net la un rezultat favorabil (``ROAS - 1``).
        fraction: Fractia din Kelly complet (``0.5`` = Half-Kelly).

    Returns:
        Fractia Kelly, in ``[-1, 1]`` (poate fi negativa).
    """
    p = min(1.0, max(0.0, win_prob))
    b = roas_odds
    if b <= 0.0:
        return round(_clamp(fraction * b), 6)
    full_kelly = (p * b - (1.0 - p)) / b
    return round(_clamp(fraction * full_kelly), 6)


def size_daily_budget(
    arms: list[ArmStats],
    *,
    baseline_cap: Decimal,
    hard_ceiling: Decimal,
    kelly_fraction: float = 0.5,
    prior_conversions: float = 1.0,
    prior_non_conversions: float = 1.0,
    break_even_roas: Decimal = Decimal("1"),
    revenue_cap: Decimal | None = None,
    allow_growth: bool = True,
) -> KellySizing:
    """Dimensioneaza plafonul zilnic absolut prin Half-Kelly, marginit de ``hard_ceiling``.

    Math:

    - ``smoothed_cvr = (conversii + a) / (click-uri + a + b)`` cu priori Beta ``a, b``
    - ``account_roas = venit_total / cost_total``; avantajul se masoara fata de
      ``break_even_roas`` (pragul de rentabilitate al clientului): ``r = account_roas /
      break_even_roas``. La un magazin cu marja 40%, ROAS 1,8 e pierdere (prag 2,5).
    - la CPC si valoare/conversie fixe, ROAS scaleaza liniar cu CVR, deci CVR-ul de
      breakeven este ``smoothed_cvr / account_roas`` iar ``win_prob`` normalizat fata
      de el se reduce la ``r / (r + 1)`` (un CVR brut ar face Kelly permanent negativ
      pentru conturi reale)
    - ``roas_odds = r - 1``
    - ``f = calculate_kelly_fraction(win_prob, roas_odds, kelly_fraction)``
    - ``multiplier = clamp(1 + f, 0.5, 2.0)`` aplicat pe ``baseline_cap``
    - ``sized_daily_cap = min(hard_ceiling, max(1.00, baseline_cap * multiplier))``

    Fail-safe: fara click-uri sau fara cost -> avantaj ``date_insuficiente``,
    plafonul se mentine la ``baseline_cap``.

    Args:
        arms: Performanta pe campanii (click-uri, conversii, cost, venit).
        baseline_cap: ``budget.max_daily_spend`` din configuratie.
        hard_ceiling: Plafonul absolut (``HARD_CEILING``).
        kelly_fraction: Fractia Kelly (``0.5`` = Half-Kelly).
        prior_conversions: Pseudo-conversii pentru netezirea CVR.
        prior_non_conversions: Pseudo-non-conversii pentru netezirea CVR.
        break_even_roas: ROAS-ul de la care contul castiga bani (implicit 1: valoarea
            conversiilor e deja castigul, ca la lead-uri).
        revenue_cap: Venitul real al contului (comenzile magazinului), cand e cunoscut.
            Venitul bratelor nu trece de el: fiecare platforma isi atribuie vanzarile ei,
            iar o vanzare vazuta de doua platforme ar intra de doua ori in ROAS.
        allow_growth: ``False`` tine plafonul cel mult la ``baseline_cap``. Fara
            comenzile magazinului, cand mai multe platforme raporteaza vanzari, ROAS-ul
            insumat poate fi umflat de vanzarile numarate de doua ori: Kelly poate taia,
            dar nu poate creste pe el.

    Returns:
        :class:`~ppc_agent.decision.models.KellySizing` cu plafonul si rationamentul.
    """
    baseline = min(_quantise(baseline_cap), _quantise(hard_ceiling))
    ceiling = _quantise(hard_ceiling)

    total_clicks = sum(arm.clicks for arm in arms)
    total_conversions = sum(arm.conversions for arm in arms)
    total_cost = sum((arm.cost for arm in arms), Decimal("0"))
    total_revenue = sum((arm.revenue for arm in arms), Decimal("0"))
    capped = revenue_cap is not None and total_revenue > revenue_cap
    if capped:
        total_revenue = max(Decimal("0"), revenue_cap or Decimal("0"))

    if total_clicks == 0 or total_cost <= 0:
        return KellySizing(
            smoothed_cvr=0.0,
            account_roas=0.0,
            win_prob=0.0,
            roas_odds=0.0,
            kelly_fraction=0.0,
            multiplier=1.0,
            baseline_cap=baseline,
            sized_daily_cap=baseline,
            hard_ceiling=ceiling,
            edge="date_insuficiente",
            rationale=(
                "Kelly: date insuficiente (fara click-uri sau fara cost). "
                f"Plafon zilnic mentinut la {baseline}."
            ),
        )

    smoothed_cvr = (total_conversions + prior_conversions) / (
        total_clicks + prior_conversions + prior_non_conversions
    )
    account_roas = float(total_revenue / total_cost)
    relative = account_roas / float(break_even_roas)
    win_prob = relative / (relative + 1.0) if relative > 0.0 else 0.0
    roas_odds = relative - 1.0

    kelly_f = calculate_kelly_fraction(win_prob, roas_odds, kelly_fraction)
    multiplier = _clamp_multiplier(1.0 + kelly_f)
    held = not allow_growth and multiplier > 1.0
    if held:
        multiplier = 1.0
    sized = min(ceiling, max(_MIN_CAP, _quantise(baseline * Decimal(str(multiplier)))))

    edge: EdgeLabel = (
        "pozitiv" if kelly_f > _EPS else "negativ" if kelly_f < -_EPS else "neutru"
    )
    return KellySizing(
        smoothed_cvr=round(smoothed_cvr, 6),
        account_roas=round(account_roas, 4),
        win_prob=round(win_prob, 6),
        roas_odds=round(roas_odds, 6),
        kelly_fraction=kelly_f,
        multiplier=round(multiplier, 4),
        baseline_cap=baseline,
        sized_daily_cap=sized,
        hard_ceiling=ceiling,
        edge=edge,
        rationale=_build_rationale(
            edge, multiplier, account_roas, baseline, sized, ceiling, break_even_roas, held=held
        )
        + (_CAPPED_NOTE if capped else "")
        + (_HELD_NOTE if held else ""),
    )


_CAPPED_NOTE = (
    " Venitul raportat de platforme e plafonat la comenzile reale ale magazinului: o "
    "vanzare vazuta de mai multe platforme se numara o data."
)
_HELD_NOTE = (
    " Plafonul nu creste: mai multe platforme raporteaza vanzari, iar fara comenzile "
    "magazinului aceeasi vanzare poate fi numarata de doua ori."
)


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _clamp_multiplier(value: float) -> float:
    return max(_MULTIPLIER_FLOOR, min(_MULTIPLIER_CEIL, value))


def _quantise(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _build_rationale(
    edge: EdgeLabel,
    multiplier: float,
    account_roas: float,
    baseline: Decimal,
    sized: Decimal,
    ceiling: Decimal,
    break_even_roas: Decimal = Decimal("1"),
    *,
    held: bool = False,
) -> str:
    pct = round((multiplier - 1.0) * 100.0)
    roas = f"ROAS {account_roas:.2f}" + (
        f", prag de rentabilitate {break_even_roas:.2f}" if break_even_roas != 1 else ""
    )
    if held:
        return f"Half-Kelly: EV pozitiv ({roas}), plafon zilnic mentinut la {baseline}."
    if edge == "pozitiv":
        return (
            f"Half-Kelly: EV pozitiv ({roas}), plafon zilnic "
            f"{baseline} -> {sized} (+{pct}%, x{multiplier:.2f}), sub plafonul "
            f"absolut {ceiling}."
        )
    if edge == "negativ":
        return (
            f"Half-Kelly: EV negativ ({roas}), plafon zilnic "
            f"redus {baseline} -> {sized} ({pct}%, x{multiplier:.2f}) pentru a "
            "pastra capitalul."
        )
    return (
        f"Half-Kelly: fara avantaj clar ({roas}), plafon zilnic "
        f"mentinut la {baseline}."
    )
