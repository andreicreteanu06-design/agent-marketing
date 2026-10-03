"""Obiectivul de campanie: axa transversala care schimba RAG-ul de copy,
payload-ul de campanie Meta si logica financiara de urmarire.

Traieste in pachetul core (nu in ``ppc_agent_server``) desi e citit dintr-un
camp de configurare a clientului (``ClientAccount.objective``, server-side):
e consumat de module core fara nicio dependinta de server (``copywriter``,
``providers``) - directia de dependinta a proiectului e intotdeauna server ->
core, niciodata invers. Serverul importa enum-ul de aici, nu il redefineste.

Niciodata ghicit: orice functie care il consuma il primeste explicit ca
argument, citit din configuratia persistata a clientului.
"""

from __future__ import annotations

import enum
from decimal import Decimal


class CampaignObjective(enum.StrEnum):
    """SALES: e-commerce, conversie tranzactionala directa (achizitie).
    LEAD_GEN: servicii/B2B, captarea unui contact (formular, telefon)."""

    SALES = "sales"
    LEAD_GEN = "lead_generation"


#: Pragul de rentabilitate al unui magazin pana se seteaza marja reala: ROAS 2, adica
#: marja de 50%. ROAS 1 (doar costul reclamelor acoperit) ar declara rentabil un cont
#: care pierde bani dupa costul marfii.
DEFAULT_SALES_MIN_ROAS = Decimal("2")
#: Sub atatea vanzari in fereastra, cosul mediu observat nu e de incredere.
MIN_ORDERS_FOR_AOV = 5
_CENT = Decimal("0.01")


def break_even_roas(objective: CampaignObjective, min_roas: Decimal | None) -> Decimal:
    """ROAS-ul de la care contul castiga bani: cel setat pe client, altfel implicitul.

    Magazinul: venitul unei vanzari include costul marfii, deci pragul e 1 / marja.
    Lead-ul: ``default_lead_value`` e deja cat valoreaza, deci pragul lui e 1.
    """
    if min_roas is not None:
        return min_roas
    return DEFAULT_SALES_MIN_ROAS if objective is CampaignObjective.SALES else Decimal("1")


def target_cpa(
    value: Decimal,
    min_roas: Decimal,
    *,
    revenue: Decimal = Decimal("0"),
    conversions: float = 0.0,
) -> Decimal:
    """CPA-ul maxim la care o conversie inca e rentabila: valoarea ei / pragul de ROAS.

    ``value`` e valoarea asteptata a unei conversii (``default_lead_value``). Cu destule
    vanzari in fereastra (``revenue``/``conversions``), cosul mediu real o inlocuieste.
    """
    if conversions >= MIN_ORDERS_FOR_AOV and revenue > 0:
        value = revenue / Decimal(str(conversions))
    return (value / min_roas).quantize(_CENT)
