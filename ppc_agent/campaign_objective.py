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


class CampaignObjective(enum.StrEnum):
    """SALES: e-commerce, conversie tranzactionala directa (achizitie).
    LEAD_GEN: servicii/B2B, captarea unui contact (formular, telefon)."""

    SALES = "sales"
    LEAD_GEN = "lead_generation"
