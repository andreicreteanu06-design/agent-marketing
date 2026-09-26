"""Piata simulata pentru Researcher, cat timp nu exista surse reale de market intelligence.

Acelasi tipar ca ``seo_geo_agent/services/intelligence_demo.py``:

- **determinist**: seed = brandul clientului + ziua, deci acelasi client vede
  aceleasi cifre toata ziua (fara sa se schimbe la fiecare intrebare), iar
  clienti diferiti vad cifre diferite;
- **construit ca sa arate fiecare regula** din ``researcher.py``: concurenti noi
  care urca CPC-ul, un sezon care porneste (indicele lunar al unui service auto:
  varfuri la schimbul de anvelope, primavara si toamna), o durere in crestere;
- **marcat mereu** ``source="demo"``: consiliul nu il foloseste in decizii si nu il
  spune clientului ca fapt. Nisa (service auto) si concurentii ("Concurentul A")
  sunt ilustrative - niciun nume real, nicio cifra a pietei reale.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ppc_agent_server.services.researcher import (
    TREND_WEEKS,
    AuctionSnapshot,
    CompetitorMove,
    DemandSeries,
    MarketSignals,
    PainTopic,
)

#: Service auto, ianuarie..decembrie (media anului = 1): schimbul de anvelope
#: urca martie-aprilie si octombrie-noiembrie.
SEASON_INDEX = (0.82, 0.78, 1.02, 1.22, 1.04, 0.95, 0.90, 0.84, 1.00, 1.24, 1.18, 1.01)
DEMO_PERIOD_DAYS = 28


@dataclass(frozen=True, slots=True)
class _DemoPain:
    theme: str
    example: str
    #: Cresterea mentiunilor fata de perioada trecuta (intervalul din care se trage).
    growth: tuple[float, float]


_PAINS = (
    _DemoPain("prețul afișat înainte de programare", "cat costa diagnoza auto", (0.40, 0.65)),
    _DemoPain("programare online în aceeași zi", "service auto programare azi", (0.28, 0.38)),
    _DemoPain("garanție la manoperă", "service auto cu garantie", (-0.05, 0.08)),
    _DemoPain("mașină la schimb pe durata reparației", "service masina la schimb", (-0.10, 0.05)),
)


def _rng(seed: str, today: date) -> random.Random:
    # Seed din sir: stabil intre rulari (nu depinde de PYTHONHASHSEED, ca hash()).
    return random.Random(f"{seed}:market:{today.isoformat()}")


def _auction(rng: random.Random) -> AuctionSnapshot:
    competitors_before = rng.randint(4, 6)
    cpc_before = Decimal(f"{rng.uniform(1.8, 2.4):.2f}")
    cpc_now = (cpc_before * Decimal(f"{rng.uniform(1.18, 1.32):.2f}")).quantize(Decimal("0.01"))
    client_before = round(rng.uniform(0.28, 0.36), 2)
    attacker_before = round(rng.uniform(0.10, 0.14), 2)
    attacker_now = round(attacker_before + rng.uniform(0.09, 0.14), 2)
    return AuctionSnapshot(
        competitors_before=competitors_before,
        competitors_now=competitors_before + rng.randint(1, 2),
        cpc_before=cpc_before,
        cpc_now=cpc_now,
        client_share_before=client_before,
        client_share_now=round(client_before - rng.uniform(0.05, 0.09), 2),
        movers=(
            CompetitorMove("Concurentul A", attacker_before, attacker_now),
            CompetitorMove("Concurentul B", 0.21, round(rng.uniform(0.19, 0.22), 2)),
            CompetitorMove("Concurentul C", 0.09, round(rng.uniform(0.07, 0.10), 2)),
        ),
    )


def _demand(rng: random.Random, today: date) -> DemandSeries:
    now = SEASON_INDEX[today.month - 1]
    ahead = SEASON_INDEX[today.month % 12]
    # Panta saptamanala urmeaza sezonul: urca spre un varf, coboara dupa el.
    slope = (ahead - now) / TREND_WEEKS
    base = rng.randint(1200, 1600) * now
    weekly = [
        round(base * (1 + slope * (week - TREND_WEEKS + 1)) * rng.uniform(0.97, 1.03))
        for week in range(TREND_WEEKS)
    ]
    recent = sum(weekly[-4:])
    return DemandSeries(
        category="service auto",
        weekly=weekly,
        same_weeks_last_year=round(recent / (1 + rng.uniform(0.06, 0.14))),
        monthly_index=SEASON_INDEX,
    )


def _pains(rng: random.Random) -> list[PainTopic]:
    pains = []
    for pain in _PAINS:
        before = rng.randint(60, 140)
        now = round(before * (1 + rng.uniform(*pain.growth)))
        pains.append(PainTopic(pain.theme, pain.example, before, now))
    return pains


def demo_market_signals(seed: str, today: date) -> MarketSignals:
    """Semnalele de piata demonstrative pentru un client (``seed`` = brandul lui)."""
    rng = _rng(seed, today)
    return MarketSignals(
        source="demo",
        market="service auto (nișă demonstrativă)",
        today=today,
        period_days=DEMO_PERIOD_DAYS,
        auction=_auction(rng),
        demand=_demand(rng, today),
        pains=_pains(rng),
    )
