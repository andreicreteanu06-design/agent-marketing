"""``GET /api/v1/proposals/{client_id}`` + ``POST /api/v1/proposals/{id}/execute``.

Poarta HITL, echivalentul DB-backed al ``ApprovalGate`` din CLI: nicio
schimbare de buget nu se aplica fara ``confirm=true`` explicit, si trece
mereu prin ``AbsoluteSpendLimiter`` inainte de executie.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ppc_agent.errors import ApprovalRequiredError
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.models import ChangeStatus, ClientAccount, ProposedChange, Tenant
from ppc_agent_server.schemas import ExecuteProposalRequest, ProposedChangeRead

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


@router.get("/{client_id}", response_model=list[ProposedChangeRead])
def list_pending_proposals(
    client_id: int,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ProposedChange]:
    """Toate modificarile in asteptare (``status=pending``) pentru un client."""
    get_owned_client(client_id, tenant, session)
    return list(
        session.exec(
            select(ProposedChange).where(
                ProposedChange.client_account_id == client_id,
                ProposedChange.status == ChangeStatus.PENDING,
            )
        ).all()
    )


def _find_owned_proposal(
    proposal_id: int, tenant: Tenant, session: Session
) -> tuple[ProposedChange, ClientAccount]:
    proposal = session.get(ProposedChange, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="propunerea nu exista")
    account = get_owned_client(proposal.client_account_id, tenant, session)
    return proposal, account


@router.post("/{proposal_id}/execute", response_model=ProposedChangeRead)
def execute_proposal(
    proposal_id: int,
    payload: ExecuteProposalRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> ProposedChange:
    """Executa (simulat) o propunere confirmata — poarta HITL DB-backed.

    Raises:
        ApprovalRequiredError: ``confirm`` nu e ``true`` (-> 403).
        SpendLimitExceeded: angajamentul zilnic total ar depasi limita
            clientului (-> 409).
    """
    proposal, account = _find_owned_proposal(proposal_id, tenant, session)

    if not payload.confirm:
        raise ApprovalRequiredError(
            "executarea necesita confirmare umana explicita (confirm=true)"
        )

    # Verifica angajamentul TOTAL (toate propunerile deja 'executed' ale
    # clientului + aceasta), nu doar randul curent — altfel N aprobari
    # individuale, fiecare sub plafon, ar putea depasi impreuna plafonul
    # absolut. Echivalentul per-propunere al verificarii pe intregul changeset
    # din ApprovalGate.flush() (CLI).
    limiter = AbsoluteSpendLimiter(account.max_daily_spend)
    already_executed = session.exec(
        select(ProposedChange).where(
            ProposedChange.client_account_id == account.id,
            ProposedChange.status == ChangeStatus.EXECUTED,
        )
    ).all()
    total_committed = sum(
        (p.projected_daily_spend for p in already_executed), Decimal("0")
    )
    limiter.check(total_committed + proposal.projected_daily_spend)

    proposal.status = ChangeStatus.EXECUTED
    proposal.decided_at = datetime.now(tz=UTC)
    proposal.decided_by = tenant.name
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
