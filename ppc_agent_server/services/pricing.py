"""Strategia de pret a consiliului: CPO-ul impacheteaza oferta, CFO-ul o leaga de valoare.

Dupa framework-ul «pricing-strategy» (mohitagw15856/pm-claude-skills), adaptat la
afacerile de servicii si magazinele clientilor - niciun rand copiat, si tot fara LLM:

- **CPO-ul**: regula celor 3 niveluri (Starter, Pro, Business). Fiecare nivel e complet
  pentru segmentul lui; Pro, pentru clientul care cumpara cel mai usor, e cea mai buna
  valoare (un nivel de mijloc mai slab impinge clientii spre extreme); Business are un
  pret minim afisat, nu doar «la cerere». Trecerea Free -> platit: un nivel gratuit doar
  cand livreaza valoare reala, costa aproape nimic si are un declansator clar de upgrade.
- **CFO-ul**: pretul NU se stabileste pe cost (cost-plus) - reflecta valoarea livrata.
  Orice oferta are un «Value Metric»: unitatea care creste odata cu valoarea primita.
- **Pozitia competitiva** (Premium / Parity / Value) se alege din date: Value doar pe o
  economie a unitatii dovedita (contul rentabil), Premium doar cu o dovada de aratat.

Niciun pret inventat: nivelurile spun CE contine fiecare si pentru cine, sumele le pune
clientul pe valoare. Preturile concurentilor nu le avem - se spune.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from ppc_agent_server.services.cpo import best_fit_segment
from ppc_agent_server.services.queen_agent import _BY_KEY, ArchetypeKey, BrandStrategyDirective
from ppc_agent_server.services.ro_format import ron as _ron

CompetitivePosition = Literal["Premium", "Parity", "Value"]


@dataclass(frozen=True, slots=True)
class _Packaging:
    #: Unitatea care creste cu valoarea primita de acest client.
    value_metric: str
    #: Intrarea gratuita care livreaza valoare reala; ``None`` = fara nivel gratuit.
    free_entry: str | None
    #: Momentul concret in care clientul trece la platit (sau la nivelul urmator).
    upgrade_trigger: str


#: Pe profilul clientului ideal (``queen_agent.ARCHETYPES``).
_PACKAGING: dict[ArchetypeKey, _Packaging] = {
    "price": _Packaging(
        "lucrarea, la preț fix spus dinainte",
        "estimarea de preț în scris",
        "acceptă prețul fix din estimare și programează lucrarea",
    ),
    "urgency": _Packaging(
        "intervenția rezolvată în aceeași zi",
        None,
        "vrea preluarea azi, nu peste o săptămână",
    ),
    "trust": _Packaging(
        "lucrarea cu garanție scrisă",
        "verificarea inițială",
        "vede garanția scrisă și recenziile, apoi cere lucrarea",
    ),
    "convenience": _Packaging(
        "serviciul complet, de la preluare la predare",
        None,
        "vrea să nu se mai ocupe el de nimic: ridicare, lucrare, predare",
    ),
    "research": _Packaging(
        "problema diagnosticată și rezolvată",
        "diagnoza sau consultanța inițială",
        "a înțeles problema din diagnoză și cere rezolvarea",
    ),
}
_SALES_METRIC = "comanda, după valoarea coșului"
_NO_PROFILE = _Packaging(
    "rezultatul livrat clientului (lucrarea sau comanda), nu ora de muncă sau materialul",
    None,
    "clientul vrea mai mult decât rezolvă pachetul de bază",
)


class PricingRecommendation(BaseModel):
    """Recomandarea de pret a consiliului - calculata determinist."""

    #: Recommended Pricing Model.
    model: str
    #: Value Metric.
    value_metric: str
    position: CompetitivePosition
    #: De ce aceasta pozitie (Competitive Position).
    position_reason: str
    #: Starter, Pro, Business - fiecare intr-o fraza (CPO-ul).
    tiers: list[str]
    #: Free-to-Paid Upgrade Trigger (CPO-ul).
    upgrade_trigger: str
    #: Directiva CFO-ului: valoare, nu cost-plus, cu ancora din date cand exista.
    value_rule: str

    def sections(self) -> str:
        """Cele trei sectiuni din framework, pentru raspunsul catre client."""
        return (
            f"Recommended Pricing Model: {self.model}\n"
            f"Value Metric: {self.value_metric}\n"
            f"Competitive Position: {self.position} - {self.position_reason}"
        )

    def cpo_brief(self) -> str:
        """Ce adauga CPO-ul in pozitia lui: pachetele si trecerea la platit."""
        return f"Pachetele (3 niveluri): {' '.join(self.tiers)} {self.upgrade_trigger}"


def _value_rule(metric: str, *, revenue: Decimal, conversions: float) -> str:
    rule = (
        "Prețul nu se stabilește pe cost (cost-plus): reflectă valoarea livrată. "
        f"Value Metric: {metric}."
    )
    if revenue > 0 and conversions > 0:
        per = (revenue / Decimal(str(conversions))).quantize(Decimal("0.01"))
        return f"{rule} O conversie aduce în medie {_ron(per)} RON: de acolo pornește prețul."
    return (
        f"{rule} Valoarea unei conversii nu o am încă (lipsesc valorile de conversie): până "
        "atunci, prețul pornește de la ce primește clientul, nu de la cost."
    )


def recommend_pricing(
    directive: BrandStrategyDirective,
    *,
    objective: str,
    profitable: bool,
    revenue: Decimal,
    conversions: float,
    reopen_when: str,
) -> PricingRecommendation:
    """Modelul, metrica de valoare, nivelurile si pozitia - din cine cumpara si din bani.

    Totul pleaca de la clientul care cumpara cel mai usor (Dunford, ca la CPO), nu
    neaparat de la cel care cauta cel mai mult: pe el il plateste oferta.
    ``profitable``: verdictul CFO-ului pe cifre de incredere. ``reopen_when``: conditia
    in care contul devine rentabil, cand nu e.
    """
    avatar = directive.avatar if directive.status == "ok" else None
    buyer = (best_fit_segment(directive) or avatar) if avatar is not None else None
    archetype = _BY_KEY[buyer.key] if buyer is not None else None
    packaging = _PACKAGING[buyer.key] if buyer is not None else _NO_PROFILE
    metric = _SALES_METRIC if objective == "sales" else packaging.value_metric

    if buyer is not None and archetype is not None:
        pro = (
            f"Pro, pentru «{buyer.name}»: oferta completă, cu {archetype.proof_points[0]} "
            "în prim-plan."
        )
    else:
        pro = "Pro, pentru clientul care cumpără cel mai des: oferta completă."
    starter = "Starter: serviciul de bază, la preț fix, cu o limită clară"
    starter += f"; intrarea gratuită: {packaging.free_entry}." if packaging.free_entry else "."
    tiers = [
        starter,
        f"{pro} E cea mai bună valoare dintre cele trei.",
        "Business: garanție extinsă, prioritate și un om de contact, cu un preț minim afișat, "
        "nu doar «la cerere».",
    ]
    if packaging.free_entry:
        model = (
            f"Pe niveluri (Tiered): Starter, Pro, Business, cu intrare gratuită "
            f"({packaging.free_entry})"
        )
        trigger = (
            f"Free -> plătit: clientul {packaging.upgrade_trigger}. Gratuitul rămâne doar cât "
            "aduce măcar 2-5% clienți plătitori."
        )
    else:
        model = "Pe niveluri (Tiered): Starter, Pro, Business, fără nivel gratuit"
        trigger = (
            f"Fără nivel gratuit: aici gratuitul ar costa o lucrare întreagă. De la Starter la "
            f"Pro trece când {packaging.upgrade_trigger}."
        )
    model += " - fiecare segment plătește pentru ce vrea, nu toți același preț."

    position: CompetitivePosition
    if not profitable:
        position = "Parity"
        reason = (
            "la prețul pieței până când "
            f"{reopen_when}: Value ar adânci pierderea, iar Premium cere o dovadă pe care "
            "cifrele nu o dau încă."
        )
    elif buyer is not None and buyer.key == "price":
        position = "Value"
        reason = (
            f"«{buyer.name}» alege după preț, iar contul e rentabil, deci economia unității "
            "susține un preț sub piață."
        )
    elif buyer is not None and archetype is not None:
        position = "Premium"
        reason = (
            f"20-40% peste piață, justificat prin {archetype.proof_points[0]}: contul e "
            f"rentabil, iar «{buyer.name}» plătește pentru asta."
        )
    else:
        position = "Parity"
        reason = "la prețul pieței: fără clientul ideal, nu am pe ce justifica altă poziție."
    reason += " Prețurile concurenților nu le am: verifică-le înainte să fixezi sumele."

    return PricingRecommendation(
        model=model,
        value_metric=metric,
        position=position,
        position_reason=reason,
        tiers=tiers,
        upgrade_trigger=trigger,
        value_rule=_value_rule(metric, revenue=revenue, conversions=conversions),
    )
