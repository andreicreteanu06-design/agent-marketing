"""Executarea unei propuneri aprobate pe platforma de reclame.

Ultimul pas al portii HITL: pana aici totul e propunere, de aici incolo se
schimba ceva real intr-un cont pe care clientul plateste bani. De asta modulul
are doua reguli pe care nu le incalca:

1. **Executa doar din ``PENDING``.** O propunere deja executata, respinsa sau
   picata nu se re-executa: un dublu-click pe butonul de aprobare nu trebuie sa
   dubleze o schimbare de buget.
2. **Nu ghiceste niciodata cum se aplica ceva.** Fiecare tip de resursa are un
   executor declarat explicit (:data:`EXECUTORS`). Un tip fara executor NU se
   aplica "pe aproape" - propunerea pica cu un mesaj care spune ce lipseste.

Modulul nu stie nimic despre HTTP si nici despre SQLModel: primeste obiectul
propunerii si un provider capabil de mutatii, si intoarce ce s-a intamplat. Persistenta
o face apelantul (vezi ``ppc_agent_server/routers/proposals.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from ppc_agent.errors import PpcAgentError

logger = logging.getLogger("ppc_agent.services.execution_engine")


class ProposalNotExecutableError(PpcAgentError):
    """Propunerea nu e intr-o stare din care se poate executa."""


class NoExecutorError(PpcAgentError):
    """Nu exista executor pentru tipul de resursa al propunerii.

    Distinct de o eroare a platformei: aici nu platforma a refuzat, ci NOI nu
    stim sa aplicam acest tip de schimbare. Mesajul o spune ca atare, ca omul
    sa nu reincerce degeaba.
    """


class MutationProvider(Protocol):
    """Ce trebuie sa stie faca un provider ca sa poata aplica o propunere.

    Deliberat mai ingusta decat ``providers.base.BaseMarketingProvider``: aici
    ne trebuie strict cele doua mutatii, iar un dublu ingust se scrie intr-un
    test fara sa implementeze si ``get_campaign_metrics``.
    """

    def pause_ad(self, ad_id: str) -> None: ...
    def scale_budget(self, campaign_id: str, new_daily_budget: Decimal) -> None: ...


class ExecutableProposal(Protocol):
    """Ce ii trebuie motorului dintr-o propunere - nu randul intreg din DB."""

    @property
    def op(self) -> str: ...
    @property
    def resource(self) -> str: ...
    @property
    def resource_type(self) -> str: ...
    @property
    def projected_daily_spend(self) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Ce s-a intamplat cu o executie. ``error`` e gol doar cand a reusit."""

    executed: bool
    detail: str
    error: str = ""


#: Cum se aplica fiecare tip de resursa: primeste providerul si propunerea, si
#: face schimbarea reala. Intoarce descrierea a ce s-a facut.
Executor = Callable[[MutationProvider, ExecutableProposal], str]


def _execute_keyword_change(
    provider: MutationProvider, proposal: ExecutableProposal
) -> str:
    """Pauza sau schimbare de buget pe o resursa de cautare platita."""
    if proposal.op == "PAUSE":
        provider.pause_ad(proposal.resource)
        return f"pauza aplicata pe '{proposal.resource}'"
    if proposal.op == "UPDATE":
        provider.scale_budget(proposal.resource, proposal.projected_daily_spend)
        return (
            f"buget zilnic actualizat pe '{proposal.resource}' la "
            f"{proposal.projected_daily_spend}"
        )
    raise NoExecutorError(
        f"operatia '{proposal.op}' nu are executor - se aplica manual in platforma"
    )


#: Registrul de executori, pe tip de resursa. Un tip care nu e aici NU se aplica
#: "pe aproape" - pica explicit cu :class:`NoExecutorError`.
EXECUTORS: dict[str, Executor] = {
    "ppc_keyword": _execute_keyword_change,
    "keyword_budget": _execute_keyword_change,
}


def execute_proposal(
    proposal: ExecutableProposal, provider: MutationProvider, *, current_status: str
) -> ExecutionResult:
    """Aplica ``proposal`` pe platforma reala si spune ce s-a intamplat.

    Args:
        current_status: starea propunerii inainte de executie. Se primeste
            explicit ca motorul sa nu depinda de enum-ul de persistenta.

    Returns:
        :class:`ExecutionResult` - ``executed=False`` cu ``error`` completat
        cand platforma a refuzat. Apelantul decide ce scrie in baza de date.

    Raises:
        ProposalNotExecutableError: propunerea nu e in ``pending``.
        NoExecutorError: tipul de resursa nu are executor.

    Cele doua exceptii sunt RIDICATE, nu intoarse ca rezultat: amandoua inseamna
    ca executia nici nu a inceput, deci propunerea trebuie sa ramana neatinsa,
    nu marcata ca picata.
    """
    if current_status != "pending":
        raise ProposalNotExecutableError(
            f"doar propunerile in asteptare se pot executa (aceasta e '{current_status}')"
        )

    executor = EXECUTORS.get(proposal.resource_type)
    if executor is None:
        raise NoExecutorError(
            f"nu exista executor pentru tipul de resursa '{proposal.resource_type}'. "
            "Propunerea ramane in asteptare - aplic-o manual in platforma."
        )

    try:
        detail = executor(provider, proposal)
    except NoExecutorError:
        raise
    except Exception as exc:
        # Orice esec al platformei (token expirat, resursa stearsa, retea) devine
        # un rezultat, nu o exceptie: propunerea trebuie marcata FAILED cu motiv,
        # ca omul sa stie daca reincercarea are sens.
        logger.warning(
            "executie esuata pentru '%s' (%s): %s: %s",
            proposal.resource,
            proposal.resource_type,
            type(exc).__name__,
            exc,
        )
        return ExecutionResult(
            executed=False,
            detail="",
            error=f"{type(exc).__name__}: {exc}",
        )

    logger.info("executat: %s", detail)
    return ExecutionResult(executed=True, detail=detail)
