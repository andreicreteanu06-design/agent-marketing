"""Cat poate plati un client pe un client nou, din costurile lui - si pana unde merg reclamele.

Doua calcule, inainte de prima campanie a unui client (le cere consiliul, in chat):

**Pragul de profit.** La un magazin, dintr-o comanda raman, inainte de reclame:

    contributia = cos * (1 - retururi) - produse * (1 - retururi) - transport - cos * comision

(un retur intoarce produsul si banii, dar transportul e pierdut). Contributia e **CAC-ul
maxim**: cat poti plati in reclame pentru o comanda fara sa pierzi bani. ROAS-ul minim e
``cos / contributie`` - la o marja de 40%, 2,5. La lead-uri: un client nou aduce un profit
``P``, iar din cereri devine client o rata ``r``: un lead valoreaza ``P * r`` (CPL-ul maxim),
un client ``P`` (CAC-ul maxim).

**Raza in jurul afacerii.** O afacere mica nu are ce face cu tot orasul: oamenii merg la o
cafenea de langa ei, dar fac drum pentru o mobila. Raza vine din tipul afacerii si din
marimea localitatii (intr-un sat, una mica n-ar avea cui sa arate reclama), plafonata la
cat vrea clientul si la limitele Meta (1-80 km).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")

BusinessKind = Literal["zilnic", "programat", "destinatie", "livrare"]
PlaceSize = Literal["oras_mare", "oras", "localitate_mica"]

#: Limitele Meta pentru o raza in jurul unei adrese.
MIN_RADIUS_KM = Decimal("1")
MAX_RADIUS_KM = Decimal("80")

#: Km, pe tip de afacere si marimea localitatii: cat merg oamenii, de obicei, pana la ea.
_RADIUS_KM: dict[BusinessKind, dict[PlaceSize, int]] = {
    # cafenea, salon, frizerie, sala, restaurant: pe drumul lor zilnic
    "zilnic": {"oras_mare": 3, "oras": 5, "localitate_mica": 10},
    # service auto, cabinet, clinica, curs: programare, cateva cartiere
    "programat": {"oras_mare": 6, "oras": 12, "localitate_mica": 20},
    # mobila, nunti, constructii, imobiliare: o achizitie mare, pentru care se face drum
    "destinatie": {"oras_mare": 20, "oras": 30, "localitate_mica": 40},
    # livrare / deplasare la client: cat acopera clientul (implicit, atat)
    "livrare": {"oras_mare": 8, "oras": 10, "localitate_mica": 15},
}

KIND_LABELS: dict[BusinessKind, str] = {
    "zilnic": "o afacere la care oamenii vin des, din apropiere",
    "programat": "o afacere cu programări",
    "destinatie": "o achiziție mare, pentru care oamenii fac drum",
    "livrare": "livrare sau deplasare la client",
}
SIZE_LABELS: dict[PlaceSize, str] = {
    "oras_mare": "într-un oraș mare",
    "oras": "într-un oraș",
    "localitate_mica": "într-o localitate mică",
}


class EconomicsError(ValueError):
    """Costurile nu lasa loc de profit: orice reclama ar pierde bani."""


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Ce poate plati clientul in reclame fara sa piarda bani."""

    #: Profitul dintr-o comanda / un client nou, inainte de reclame = CAC-ul maxim.
    max_cac: Decimal
    #: ROAS-ul de la care reclamele sunt profitabile (1 la lead-uri: valoarea e profit).
    break_even_roas: Decimal
    #: Cat valoreaza o conversie in planul de buget: cosul (magazin) sau ``P * r`` (lead).
    conversion_value: Decimal
    #: CPL-ul maxim la lead-uri (``None`` la magazine).
    max_cpl: Decimal | None = None

    @property
    def margin_pct(self) -> Decimal:
        """Marja de contributie, in procente (doar informativ)."""
        return (_HUNDRED / self.break_even_roas).quantize(_CENT)


def shop_thresholds(
    *,
    average_order_value: Decimal,
    product_cost: Decimal,
    shipping_cost: Decimal,
    payment_fee_pct: Decimal,
    return_rate_pct: Decimal,
) -> Thresholds:
    """Pragurile unui magazin dintr-o comanda medie.

    Raises:
        EconomicsError: contributia nu e pozitiva - magazinul pierde bani inainte de reclame.
    """
    if average_order_value <= 0:
        raise EconomicsError("valoarea medie a unei comenzi trebuie să fie mai mare decât 0")
    kept = 1 - return_rate_pct / _HUNDRED
    contribution = (
        average_order_value * kept
        - product_cost * kept
        - shipping_cost
        - average_order_value * payment_fee_pct / _HUNDRED
    ).quantize(_CENT)
    if contribution <= 0:
        raise EconomicsError(
            f"din cifrele tale, o comandă de {average_order_value} lei lasă {contribution} lei "
            "înainte de reclame - orice reclamă ar adăuga pierdere. Verifică prețul și costurile."
        )
    return Thresholds(
        max_cac=contribution,
        break_even_roas=(average_order_value / contribution).quantize(_CENT, ROUND_CEILING),
        conversion_value=average_order_value,
    )


def lead_thresholds(*, customer_profit: Decimal, close_rate_pct: Decimal) -> Thresholds:
    """Pragurile unei afaceri cu lead-uri: profitul unui client si rata de inchidere.

    Raises:
        EconomicsError: profit sau rata de inchidere nule.
    """
    if customer_profit <= 0 or close_rate_pct <= 0:
        raise EconomicsError(
            "un client nou trebuie să aducă profit, iar măcar o parte din cereri să devină "
            "clienți - altfel reclamele nu au cum să fie profitabile"
        )
    lead_value = (customer_profit * close_rate_pct / _HUNDRED).quantize(_CENT)
    return Thresholds(
        max_cac=customer_profit.quantize(_CENT),
        break_even_roas=Decimal("1"),
        conversion_value=lead_value,
        max_cpl=lead_value,
    )


def place_size(population: int | None, place_type: str) -> PlaceSize:
    """Marimea localitatii, din populatie (cand o stim) sau din tipul ei in OpenStreetMap."""
    if population is not None:
        if population >= 200_000:
            return "oras_mare"
        return "oras" if population >= 20_000 else "localitate_mica"
    return "oras" if place_type == "city" else "localitate_mica"


@dataclass(frozen=True, slots=True)
class RadiusChoice:
    radius_km: Decimal
    reason: str


def choose_radius(
    kind: BusinessKind, size: PlaceSize, client_max_km: Decimal | None
) -> RadiusChoice:
    """Raza reclamelor in jurul afacerii, cu motivul ei, spus clientului."""
    logical = Decimal(_RADIUS_KM[kind][size])
    reason = (
        f"Pentru {KIND_LABELS[kind]} {SIZE_LABELS[size]}, clienții vin de obicei de "
        f"pe o rază de circa {logical} km"
    )
    radius = logical
    if client_max_km is not None and client_max_km < logical:
        radius = client_max_km
        reason += f"; ai cerut cel mult {client_max_km} km, deci rămân la atât"
    elif client_max_km is not None and client_max_km > logical:
        reason += (
            f". Ai fi mers până la {client_max_km} km, dar încep cu {logical}: mai departe, "
            "banii ajung la oameni care rar fac drumul. Lărgesc raza când reclamele aduc "
            "clienți profitabili din apropiere"
        )
    radius = min(MAX_RADIUS_KM, max(MIN_RADIUS_KM, radius))
    return RadiusChoice(radius_km=radius, reason=reason + ".")
