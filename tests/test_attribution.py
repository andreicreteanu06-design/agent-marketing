"""Teste pentru atribuirea Markov, cu un caz verificabil manual."""

from __future__ import annotations

import pytest

from ppc_agent.decision.attribution import Journey, attribute, removal_effects
from ppc_agent.errors import AttributionError


def _two_channel_journeys() -> list[Journey]:
    """Setul de referinta pentru cazul calculat manual (canale A si B).

    J1: A -> B -> conversie
    J2: B -> A -> null
    J3: A -> conversie
    J4: B -> conversie
    """
    return [
        Journey(["A", "B"], converted=True),
        Journey(["B", "A"], converted=False),
        Journey(["A"], converted=True),
        Journey(["B"], converted=True),
    ]


def test_two_channel_removal_effects_match_hand_calculation() -> None:
    """Matrice de tranzitie -> (I - Q) x = r.

    Rezolvare pe hartie: x_A = 5/8, x_B = 7/8, x_start = 3/4 -> P(conv) = 0.75.
    Eliminare A: P = 1/3  -> removal(A) = 1 - (1/3)/(3/4) = 5/9.
    Eliminare B: P = 1/6  -> removal(B) = 1 - (1/6)/(3/4) = 7/9.
    """
    effects = removal_effects(_two_channel_journeys())
    assert effects["A"] == pytest.approx(5 / 9, abs=1e-9)
    assert effects["B"] == pytest.approx(7 / 9, abs=1e-9)


def test_two_channel_attribution_matches_hand_calculation() -> None:
    """Suma efectelor = 4/3; 3 conversii observate.

    Markov: A = 3 * (5/9)/(4/3) = 1.25 ; B = 3 * (7/9)/(4/3) = 1.75.
    Last-click: ultimul canal al parcursurilor care convertesc -> A=1, B=2.
    """
    result = attribute(_two_channel_journeys())
    assert result.total_conversions == pytest.approx(3.0)
    assert result.base_conversion_probability == pytest.approx(0.75, abs=1e-9)

    by_channel = {channel.channel: channel for channel in result.channels}
    assert by_channel["A"].markov_conversions == pytest.approx(1.25, abs=1e-6)
    assert by_channel["B"].markov_conversions == pytest.approx(1.75, abs=1e-6)
    assert by_channel["A"].last_click_conversions == pytest.approx(1.0, abs=1e-6)
    assert by_channel["B"].last_click_conversions == pytest.approx(2.0, abs=1e-6)


def test_markov_and_last_click_disagree() -> None:
    result = attribute(_two_channel_journeys())
    disagreements = [
        c for c in result.channels
        if abs(c.markov_conversions - c.last_click_conversions) > 1e-6
    ]
    assert disagreements, "atribuirea Markov ar trebui sa difere de last-click"


def test_markov_conversions_sum_to_total() -> None:
    result = attribute(_two_channel_journeys(), total_conversions=10.0)
    assert sum(c.markov_conversions for c in result.channels) == pytest.approx(10.0, abs=1e-6)


def test_single_channel_removal_effect_is_one() -> None:
    journeys = [
        Journey(["Solo"], converted=True),
        Journey(["Solo"], converted=True),
        Journey(["Solo"], converted=False),
    ]
    effects = removal_effects(journeys)
    assert effects["Solo"] == pytest.approx(1.0, abs=1e-9)


def test_empty_journeys_raises() -> None:
    with pytest.raises(AttributionError):
        removal_effects([])


def test_no_conversions_raises() -> None:
    journeys = [Journey(["A"], converted=False), Journey(["B"], converted=False)]
    with pytest.raises(AttributionError):
        attribute(journeys)


def test_journey_from_tokens_reads_outcome() -> None:
    converted = Journey.from_tokens(["Email", "Search", "conversion"])
    lost = Journey.from_tokens(["Display", "null"])
    assert converted.path == ("Email", "Search")
    assert converted.converted is True
    assert lost.path == ("Display",)
    assert lost.converted is False
