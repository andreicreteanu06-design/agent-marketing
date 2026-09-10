"""Atribuire prin lanturi Markov, cu efect de eliminare rezolvat analitic.

Fara simulare: probabilitatea de absorbtie in starea ``conversie`` se obtine
rezolvand sistemul ``(I - Q) x = r``, unde ``Q`` este submatricea tranzienta a
matricei de tranzitie, iar ``r`` coloana catre ``conversie``. Este echivalent cu
matricea fundamentala ``N = (I - Q)^-1`` aplicata pe ``r``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray

from ppc_agent.decision.models import AttributionResult, ChannelAttribution
from ppc_agent.errors import AttributionError

_START = "__start__"
_CONVERSION = "__conversie__"
_NULL = "__null__"
_CONVERTED_MARKERS = frozenset({"conversion", "conversie", "convert", "1", "true"})

FloatArray = NDArray[np.float64]


class Journey:
    """Un parcurs de client: o secventa ordonata de puncte de contact + rezultat."""

    __slots__ = ("converted", "path")

    def __init__(self, path: Sequence[str], converted: bool) -> None:
        """Creeaza un parcurs.

        Args:
            path: Punctele de contact in ordine (canale / campanii).
            converted: ``True`` daca parcursul s-a incheiat cu o conversie.
        """
        self.path: tuple[str, ...] = tuple(path)
        self.converted: bool = converted

    @classmethod
    def from_tokens(cls, tokens: Sequence[str]) -> Journey:
        """Construieste dintr-o lista ``[canal1, ..., "conversion"|"null"]``."""
        items = list(tokens)
        if not items:
            raise AttributionError("parcurs gol")
        last = items[-1].strip().lower()
        if last in _CONVERTED_MARKERS:
            return cls(items[:-1], converted=True)
        if last in {"null", "none", "0", "false"}:
            return cls(items[:-1], converted=False)
        return cls(items, converted=False)


def _transition_matrix(journeys: list[Journey]) -> tuple[list[str], FloatArray]:
    """Construieste lista de stari si matricea de tranzitie normalizata pe randuri."""
    channels: list[str] = []
    seen: set[str] = set()
    for journey in journeys:
        for channel in journey.path:
            if channel not in seen:
                seen.add(channel)
                channels.append(channel)

    states = [_START, *channels, _CONVERSION, _NULL]
    index = {state: i for i, state in enumerate(states)}
    counts: FloatArray = np.zeros((len(states), len(states)), dtype=np.float64)

    for journey in journeys:
        outcome = _CONVERSION if journey.converted else _NULL
        nodes = [_START, *journey.path, outcome]
        for src, dst in pairwise(nodes):
            counts[index[src], index[dst]] += 1.0

    counts[index[_CONVERSION], index[_CONVERSION]] = 1.0
    counts[index[_NULL], index[_NULL]] = 1.0

    row_sums: FloatArray = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0.0] = 1.0
    matrix: FloatArray = counts / row_sums
    return states, matrix


def _conversion_probability(
    states: list[str], matrix: FloatArray, blocked: str | None = None
) -> float:
    """Probabilitatea de a ajunge in ``conversie`` pornind din ``start``.

    Daca ``blocked`` este dat, canalul respectiv devine o fundatura catre ``null``
    (efectul de eliminare): toate tranzitiile lui sunt redirectate spre ``null``.
    """
    index = {state: i for i, state in enumerate(states)}
    transient = [s for s in states if s not in (_CONVERSION, _NULL)]
    t_index = {state: i for i, state in enumerate(transient)}

    working: FloatArray = matrix.copy()
    if blocked is not None and blocked in index:
        working[index[blocked], :] = 0.0
        working[index[blocked], index[_NULL]] = 1.0

    size = len(transient)
    q: FloatArray = np.zeros((size, size), dtype=np.float64)
    r: FloatArray = np.zeros(size, dtype=np.float64)
    for src in transient:
        for dst in transient:
            q[t_index[src], t_index[dst]] = working[index[src], index[dst]]
        r[t_index[src]] = working[index[src], index[_CONVERSION]]

    absorption = np.linalg.solve(np.eye(size) - q, r)
    return float(absorption[t_index[_START]])


def removal_effects(journeys: list[Journey]) -> dict[str, float]:
    """Efectul de eliminare pentru fiecare canal.

    Math: ``removal_effect(c) = 1 - P(conv | c eliminat) / P(conv | graf complet)``.
    Ambele probabilitati se obtin analitic din ``(I - Q) x = r``.

    Args:
        journeys: Parcursurile de client.

    Returns:
        Dictionar canal -> efect de eliminare (in general in ``[0, 1]``).

    Raises:
        AttributionError: Daca nu exista parcursuri sau nicio conversie.
    """
    if not journeys:
        raise AttributionError("este nevoie de cel putin un parcurs")

    states, matrix = _transition_matrix(journeys)
    channels = [s for s in states if s not in (_START, _CONVERSION, _NULL)]
    baseline = _conversion_probability(states, matrix)
    if baseline <= 0.0:
        raise AttributionError("nicio conversie observata in parcursuri")

    effects: dict[str, float] = {}
    for channel in channels:
        without = _conversion_probability(states, matrix, blocked=channel)
        effects[channel] = 1.0 - without / baseline
    return effects


def attribute(
    journeys: list[Journey], total_conversions: float | None = None
) -> AttributionResult:
    """Distribuie conversiile pe canale prin efectul de eliminare Markov.

    Inlocuieste modelele last-click / data-driven implicite. Returneaza si
    atribuirea last-click pe aceleasi parcursuri, pentru comparatie.

    Args:
        journeys: Parcursurile de client.
        total_conversions: Totalul de distribuit. Implicit: numarul de parcursuri
            care au convertit.

    Returns:
        Rezultatul atribuirii, cu efect de eliminare, conversii Markov si
        last-click per canal.

    Raises:
        AttributionError: Daca intrarea este goala, fara conversii, sau daca suma
            efectelor de eliminare este zero.
    """
    effects = removal_effects(journeys)
    states, matrix = _transition_matrix(journeys)
    baseline = _conversion_probability(states, matrix)

    converted = [journey for journey in journeys if journey.converted]
    observed = float(len(converted))
    total = observed if total_conversions is None else float(total_conversions)

    effect_sum = sum(effects.values())
    if effect_sum <= 0.0:
        raise AttributionError("suma efectelor de eliminare este zero")

    last_click_counts: Counter[str] = Counter(
        journey.path[-1] for journey in converted if journey.path
    )
    last_click_total = float(sum(last_click_counts.values())) or 1.0

    channels = [
        ChannelAttribution(
            channel=channel,
            removal_effect=round(effect, 6),
            markov_conversions=round(total * effect / effect_sum, 6),
            last_click_conversions=round(
                total * last_click_counts.get(channel, 0) / last_click_total, 6
            ),
        )
        for channel, effect in sorted(
            effects.items(), key=lambda item: item[1], reverse=True
        )
    ]
    return AttributionResult(
        total_conversions=total,
        base_conversion_probability=round(baseline, 6),
        channels=channels,
    )
