"""Analizele care ies din IMBINAREA datelor platite cu cele organice.

Aici sta partea pe care un tool de SEO nu o poate produce, oricat de mare i-ar
fi indexul: el nu stie cat platesti pe fiecare interogare si care dintre ele
aduc bani. Noi avem ambele surse in acelasi loc - contul de Google Ads al
clientului (cheltuiala, conversii, CPA) si Search Console (pozitia organica
reala pe aceleasi interogari).

Doua analize, ambele functii pure peste randuri deja aduse:

1. :class:`CannibalizationDetector` - interogari unde site-ul e DEJA in primele
   pozitii organice, dar continuam sa platim pentru ele. Nu spune automat "taie
   bugetul": incrementalitatea e reala si se masoara cu un test, nu se presupune.
   Spune "aici merita testat", cu cifra de economie potentiala atasata.

2. :class:`SeoOpportunityFinder` - interogari care CONVERTESC platit, dar unde
   organic nu existam. Alea sunt brief-urile de continut care se justifica cu
   bani, nu cu volum estimat.

Ambele intorc obiecte cu dovada la ele (cheltuiala, conversii, pozitie), ca
recomandarea sa poata fi verificata, nu crezuta pe cuvant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: De la ce pozitie in sus consideram ca organicul "acopera" deja interogarea.
#: 3 nu e arbitrar: sub primele trei rezultate, CTR-ul organic scade abrupt,
#: deci reclama chiar aduce trafic incremental.
TOP_ORGANIC_POSITION = 3.0
#: Peste ce pozitie consideram ca organic practic nu existam (pagina 2+).
WEAK_ORGANIC_POSITION = 10.0
#: Sub atatea conversii, cifrele nu sunt un semnal - sunt zgomot.
MIN_CONVERSIONS_FOR_SIGNAL = 1.0


@dataclass(frozen=True, slots=True)
class PaidSearchTerm:
    """O interogare reala care a declansat reclame, cu rezultatul ei financiar."""

    term: str
    clicks: int
    cost: Decimal
    conversions: float
    conversions_value: Decimal

    @property
    def cpa(self) -> Decimal | None:
        """Cost pe achizitie; ``None`` cand nu exista conversii (nu zero - lipsa)."""
        if self.conversions <= 0:
            return None
        return self.cost / Decimal(str(self.conversions))

    @property
    def roas(self) -> float:
        return float(self.conversions_value / self.cost) if self.cost > 0 else 0.0


@dataclass(frozen=True, slots=True)
class OrganicPosition:
    """Pozitia organica a site-ului propriu pe o interogare."""

    query: str
    position: float
    clicks: int
    impressions: int


@dataclass(frozen=True, slots=True)
class CannibalizationFinding:
    """Platim pentru o interogare pe care o detinem deja organic."""

    term: str
    organic_position: float
    paid_clicks: int
    paid_cost: Decimal
    paid_conversions: float
    #: Cheltuiala pe ultima perioada analizata - limita superioara a economiei,
    #: NU economia garantata: o parte din click-uri nu s-ar muta pe organic.
    potential_monthly_saving: Decimal


@dataclass(frozen=True, slots=True)
class SeoOpportunity:
    """O interogare care aduce bani platit, dar unde organic nu existam."""

    term: str
    paid_conversions: float
    paid_cost: Decimal
    paid_cpa: Decimal | None
    roas: float
    #: ``None`` = nu aparem deloc in Search Console pe acest termen.
    organic_position: float | None


def _normalize(term: str) -> str:
    """Interogarile vin din doua sisteme diferite; le aducem la aceeasi forma."""
    return " ".join(term.lower().split())


class CannibalizationDetector:
    """Gaseste interogarile pe care le platim desi le detinem organic."""

    def __init__(self, *, top_position: float = TOP_ORGANIC_POSITION) -> None:
        self._top_position = top_position

    def find(
        self, paid_terms: list[PaidSearchTerm], organic: list[OrganicPosition]
    ) -> list[CannibalizationFinding]:
        """Interogarile din ``paid_terms`` unde pozitia organica e in top.

        Sortate dupa cheltuiala, descrescator: prima din lista e cea unde un
        test de oprire a reclamei ar avea cel mai mare efect asupra bugetului.
        """
        organic_by_term = {_normalize(row.query): row for row in organic}
        findings: list[CannibalizationFinding] = []
        for paid in paid_terms:
            match = organic_by_term.get(_normalize(paid.term))
            if match is None or match.position > self._top_position:
                continue
            if paid.cost <= 0:
                continue
            findings.append(
                CannibalizationFinding(
                    term=paid.term,
                    organic_position=match.position,
                    paid_clicks=paid.clicks,
                    paid_cost=paid.cost,
                    paid_conversions=paid.conversions,
                    potential_monthly_saving=paid.cost,
                )
            )
        findings.sort(key=lambda item: item.paid_cost, reverse=True)
        return findings


class SeoOpportunityFinder:
    """Gaseste interogarile care convertesc platit si unde organic lipsim."""

    def __init__(
        self,
        *,
        weak_position: float = WEAK_ORGANIC_POSITION,
        min_conversions: float = MIN_CONVERSIONS_FOR_SIGNAL,
    ) -> None:
        self._weak_position = weak_position
        self._min_conversions = min_conversions

    def find(
        self, paid_terms: list[PaidSearchTerm], organic: list[OrganicPosition]
    ) -> list[SeoOpportunity]:
        """Oportunitatile, sortate dupa conversii - nu dupa volum estimat.

        Ordinea asta e intentionata: un cuvant cu 40.000 de cautari lunare si
        zero conversii nu merita un articol, unul cu 90 de cautari si 12
        conversii merita.
        """
        organic_by_term = {_normalize(row.query): row for row in organic}
        opportunities: list[SeoOpportunity] = []
        for paid in paid_terms:
            if paid.conversions < self._min_conversions:
                continue
            match = organic_by_term.get(_normalize(paid.term))
            if match is not None and match.position <= self._weak_position:
                continue  # deja ranchezi decent - nu e un gol
            opportunities.append(
                SeoOpportunity(
                    term=paid.term,
                    paid_conversions=paid.conversions,
                    paid_cost=paid.cost,
                    paid_cpa=paid.cpa,
                    roas=paid.roas,
                    organic_position=match.position if match else None,
                )
            )
        opportunities.sort(key=lambda item: item.paid_conversions, reverse=True)
        return opportunities
