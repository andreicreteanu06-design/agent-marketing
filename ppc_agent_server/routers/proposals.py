"""Poarta HITL: propunerile si trecerea lor in schimbari reale.

Doua familii de rute, dupa cine intreaba:

- **agentie** (cheie API): ``GET /{client_id}``, ``POST /{id}/execute`` - ce
  exista de la inceput, pentru operarea din partea agentiei;
- **client** (token JWT, zona ``/cont``): ``GET /pending``,
  ``POST /{id}/approve``, ``POST /{id}/reject`` - butoanele din interfata lui.

Ambele trec prin aceleasi doua garantii: nicio schimbare fara confirmare
umana explicita, si ``AbsoluteSpendLimiter`` inainte de orice executie.

ORDINEA DECLARARII CONTEAZA: ``/pending`` trebuie sa stea INAINTEA lui
``/{client_id}``, altfel FastAPI incearca sa parseze "pending" ca int si
raspunde 422. De asta rutele de client stau in acelasi fisier, nu intr-unul
separat inclus dupa - o dependenta de ordine intre fisiere e o capcana.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ppc_agent.errors import ApprovalRequiredError
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.services.execution_engine import (
    MutationProvider,
    NoExecutorError,
    ProposalNotExecutableError,
)
from ppc_agent.services.execution_engine import (
    # Aliasat: endpoint-ul agentiei din acest fisier se numeste tot
    # execute_proposal, si e o cu totul alta functie.
    execute_proposal as run_execution,
)
from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import (
    ChangeStatus,
    ClientAccount,
    ClientUser,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import ExecuteProposalRequest, ProposedChangeRead

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


def _mutation_provider(account: ClientAccount) -> MutationProvider | None:
    """Providerul prin care s-ar aplica schimbarile pentru acest client.

    ``None`` cand nu exista niciunul - si azi asta e cazul, pentru toti.

    Starea reala a codului, ca sa nu para altceva: singurul ABC din
    ``providers/base.py`` care declara mutatii (``pause_ad``/``scale_budget``)
    e ``BaseMarketingProvider``, implementat de o singura clasa
    (``LiveGenerativeEngineProvider``, stub pentru OpenAI Ads).
    ``GoogleAdsProvider`` si ``MetaMarketingProvider`` sunt contracte de
    CITIRE - nu declara nicio mutatie, iar ``ProviderFactory`` nu are nicio
    metoda care sa intoarca un provider capabil de scriere.

    Deci lantul e complet si testat pana la ultima veriga, iar veriga aia
    lipseste din contractul providerilor, nu din codul asta. Cand un provider
    capata mutatii reale, se schimba DOAR functia asta.
    """
    _ = ProviderFactory(_app_config_for(account))
    return None


def _check_spend_limit(
    session: Session, account: ClientAccount, proposal: ProposedChange
) -> None:
    """Verifica angajamentul TOTAL al clientului, nu doar randul curent.

    Altfel N aprobari individuale, fiecare sub plafon, ar putea depasi impreuna
    plafonul absolut. Echivalentul per-propunere al verificarii pe intregul
    changeset din ``ApprovalGate.flush()`` (CLI).
    """
    already_executed = session.exec(
        select(ProposedChange).where(
            ProposedChange.client_account_id == account.id,
            ProposedChange.status == ChangeStatus.EXECUTED,
        )
    ).all()
    total_committed = sum(
        (p.projected_daily_spend for p in already_executed), Decimal("0")
    )
    AbsoluteSpendLimiter(account.max_daily_spend).check(
        total_committed + proposal.projected_daily_spend
    )


def _client_proposal(
    proposal_id: int, client_user: ClientUser, session: Session
) -> tuple[ProposedChange, ClientAccount]:
    """Propunerea ``proposal_id``, doar daca e a clientului autentificat.

    404 si cand exista, dar e a altuia - acelasi raspuns pentru "nu exista" si
    "nu e a ta", ca un id ghicit sa nu confirme nimic.
    """
    proposal = session.get(ProposedChange, proposal_id)
    if proposal is None or proposal.client_account_id != client_user.client_account_id:
        raise HTTPException(status_code=404, detail="propunerea nu exista")
    account = session.get(ClientAccount, proposal.client_account_id)
    if account is None:  # pragma: no cover - FK garanteaza existenta
        raise HTTPException(status_code=404, detail="contul clientului nu exista")
    return proposal, account


@router.get("/pending", response_model=list[ProposedChangeRead])
def list_my_pending_proposals(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ProposedChange]:
    """Propunerile in asteptare ale clientului autentificat (tabloul lui de bord).

    Cele mai noi primele: coada de aprobari se citeste de sus in jos.
    """
    return list(
        session.exec(
            select(ProposedChange)
            .where(ProposedChange.client_account_id == client_user.client_account_id)
            .where(ProposedChange.status == ChangeStatus.PENDING)
            .order_by(ProposedChange.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


@router.post("/{proposal_id}/approve", response_model=ProposedChangeRead)
def approve_proposal(
    proposal_id: int,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProposedChange:
    """Aproba o propunere SI o aplica pe platforma.

    Singurul loc din tot lantul unde se schimba ceva real intr-un cont de
    reclame. Ordinea e intentionata: intai plafonul de cheltuiala, apoi
    executia, apoi scrierea starii - ca o propunere sa nu ajunga niciodata
    marcata executata fara ca platforma sa fi confirmat.

    Raises:
        HTTPException: 404 propunere inexistenta/a altuia, 409 stare gresita
            sau lipsa de executor, 502 platforma a refuzat.
        SpendLimitExceeded: plafonul zilnic ar fi depasit (-> 409).
    """
    proposal, account = _client_proposal(proposal_id, client_user, session)
    _check_spend_limit(session, account, proposal)

    provider = _mutation_provider(account)
    if provider is None:
        # 501, nu FAILED: nu am incercat si nu am esuat - nu avem cu ce. Propunerea
        # ramane PENDING, ca sa poata fi aplicata manual sau automat mai tarziu.
        raise HTTPException(
            status_code=501,
            detail=(
                "Nu exista inca un provider care sa aplice schimbari pe platforma. "
                "Propunerea ramane in asteptare - aplic-o manual in contul de reclame."
            ),
        )
    try:
        result = run_execution(proposal, provider, current_status=proposal.status.value)
    except ProposalNotExecutableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NoExecutorError as exc:
        # Propunerea ramane PENDING: nu platforma a refuzat, ci noi nu stim
        # sa aplicam tipul asta. A o marca FAILED ar sugera ca s-a incercat.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    decided_at = datetime.now(tz=UTC)
    if result.executed:
        proposal.status = ChangeStatus.EXECUTED
        proposal.error_message = None
    else:
        proposal.status = ChangeStatus.FAILED
        proposal.error_message = result.error
    proposal.decided_at = decided_at
    proposal.decided_by = client_user.email
    session.add(proposal)
    session.commit()
    session.refresh(proposal)

    if not result.executed:
        raise HTTPException(
            status_code=502,
            detail=f"platforma a refuzat schimbarea: {result.error}",
        )
    return proposal


@router.post("/{proposal_id}/reject", response_model=ProposedChangeRead)
def reject_proposal(
    proposal_id: int,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProposedChange:
    """Respinge o propunere. Nu atinge nicio platforma - doar scrie starea."""
    proposal, _ = _client_proposal(proposal_id, client_user, session)
    if proposal.status is not ChangeStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=(
                "doar propunerile in asteptare se pot respinge "
                f"(aceasta e '{proposal.status.value}')"
            ),
        )
    proposal.status = ChangeStatus.REJECTED
    proposal.decided_at = datetime.now(tz=UTC)
    proposal.decided_by = client_user.email
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


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
