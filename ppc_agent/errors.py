"""Tipuri de exceptii partajate de toate modulele agentului PPC."""

from __future__ import annotations


class PpcAgentError(Exception):
    """Clasa de baza pentru toate erorile agentului PPC."""


class SetupRequiredError(PpcAgentError):
    """Ridicata cand se cere modul ``live`` fara integrarea / credentialele necesare.

    In versiunea 1 modul ``live`` este un stub: orice apel catre un furnizor
    ``live`` ridica aceasta eroare cu instructiuni de configurare. Niciun apel de
    retea nu este efectuat.
    """


class ApprovalRequiredError(PpcAgentError):
    """Ridicata cand se incearca executarea unui set de modificari neconfirmat.

    Vezi Modulul 4 (:mod:`ppc_agent.guardrails`). Nicio operatie de scriere nu
    poate ocoli fluxul ``propose -> flush -> confirmare umana``.
    """


class SpendLimitExceeded(PpcAgentError):
    """Ridicata cand cheltuiala zilnica propusa depaseste limita permisa.

    Sursa limitei: fie ``budget.max_daily_spend`` din configuratie, fie plafonul
    absolut hardcodat in :mod:`ppc_agent.guardrails` (Modulul 4).
    """


class CrawlError(PpcAgentError):
    """Eroare la accesarea unei pagini de catre crawler (Modulul 1)."""


class CrawlTimeoutError(CrawlError):
    """Pagina nu a raspuns in intervalul de timp alocat."""
