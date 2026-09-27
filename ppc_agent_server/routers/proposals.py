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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlmodel import Session, col, select

from ppc_agent.config import ProviderMode
from ppc_agent.errors import ApprovalRequiredError, SpendLimitExceeded
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.services.execution_engine import (
    PLATFORM_META,
    MetaMutationProvider,
    NoExecutorError,
    ProposalNotExecutableError,
    ResourceTarget,
    resolve_target,
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
from ppc_agent_server.spend_guard import check_spend_limit

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


def _require_mutation_provider(
    account: ClientAccount, target: ResourceTarget
) -> MetaMutationProvider:
    """Providerul prin care se aplica schimbarea, sau 409 cu motivul exact.

    Trei motive pentru care nu se poate aplica, si fiecare spune omului altceva
    de facut - de-asta nu au acelasi mesaj:

    1. **Alta platforma decat Meta.** ``GoogleAdsProvider`` si
       ``TikTokAdsProvider`` sunt contracte de CITIRE: n-au nicio metoda de
       mutatie si nicio implementare in spate. Propunerile motorului hibrid
       (termeni de cautare Google Ads) cad aici.
    2. **Mod ``mock``.** Nu aplicam nimic si nu ne prefacem ca am aplicat.
    3. **Cont Meta neconectat.** Lipseste token-ul.

    In toate trei propunerea ramane ``pending``, ca sa poata fi aplicata manual
    sau automat mai tarziu.

    Raises:
        HTTPException: 409, cu motivul de mai sus.
    """
    if target.platform != PLATFORM_META:
        raise HTTPException(
            status_code=409,
            detail=(
                f"schimbarile pe {target.platform} nu se pot aplica automat inca - "
                "doar Meta are provider de scriere. Propunerea ramane in asteptare; "
                "aplic-o manual in platforma."
            ),
        )
    config = _app_config_for(account)
    if config.provider_mode is not ProviderMode.LIVE:
        raise HTTPException(
            status_code=409,
            detail=(
                "serverul ruleaza in mod mock (PPC_PROVIDER_MODE), deci nu aplica "
                "schimbari reale. Propunerea ramane in asteptare."
            ),
        )
    provider = ProviderFactory(config).meta_mutations()
    if provider is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "contul Meta nu e conectat (lipseste token-ul de acces). "
                "Conecteaza-l din setarile contului si reincearca."
            ),
        )
    return provider


def _check_spend_limit(
    session: Session, account: ClientAccount, proposal: ProposedChange
) -> None:
    """Angajamentul TOTAL al clientului plus aceasta propunere - vezi ``spend_guard``."""
    check_spend_limit(session, account, proposal.projected_daily_spend)


def _transition(
    session: Session, proposal: ProposedChange, *, frm: ChangeStatus, to: ChangeStatus
) -> bool:
    """Muta propunerea din ``frm`` in ``to`` ATOMIC, printr-un singur UPDATE conditionat.

    ``UPDATE ... SET status=:to WHERE id=:id AND status=:frm`` - baza de date
    serializeaza scrierile, deci din doua cereri simultane (dublu click pe
    «Aprobă», aprobare si respingere in acelasi timp) exact una schimba randul.
    Cealalta vede 0 randuri afectate si primeste ``False`` - nu mai pleaca a
    doua oara spre platforma.
    """
    result = session.exec(
        update(ProposedChange)
        .where(col(ProposedChange.id) == proposal.id, col(ProposedChange.status) == frm)
        .values(status=to)
    )
    session.commit()
    session.refresh(proposal)
    return result.rowcount == 1


def _already_decided(action: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            f"propunerea tocmai a fost preluata de alta cerere - nu o {action} a doua oara "
            "(reincarca lista)"
        ),
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


@router.get("/blocked", response_model=list[ProposedChangeRead])
def list_my_blocked_proposals(
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ProposedChange]:
    """Propunerile oprite de consiliu in tura de noapte, cu motivul (``error_message``).

    Veto-ul Tehnicianului sau restrictia CFO-ului (``services/council_guard.py``): de
    aici afla clientul de ce nu s-a lansat o campanie sau n-a crescut un buget.
    """
    return list(
        session.exec(
            select(ProposedChange)
            .where(ProposedChange.client_account_id == client_user.client_account_id)
            .where(ProposedChange.status == ChangeStatus.BLOCKED)
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
    reclame. Ordinea e intentionata: starea, plafonul de cheltuiala, tinta
    (ce platforma, ce obiect), providerul, abia apoi executia si scrierea
    starii - ca o propunere sa nu ajunga niciodata marcata executata fara ca
    platforma sa fi confirmat, si ca tot ce se poate refuza sa se refuze
    INAINTE de primul apel catre platforma.

    Raises:
        HTTPException: 404 propunere inexistenta/a altuia, 409 stare gresita /
            resursa neadresabila / lipsa de provider, 502 platforma a refuzat.
        SpendLimitExceeded: plafonul zilnic ar fi depasit (-> 409).

    Un 409 lasa propunerea PENDING (nu s-a incercat nimic); un 502 o lasa
    FAILED cu motivul de la platforma. Distinctia conteaza in interfata: prima
    se poate reincerca dupa ce se schimba ceva la noi, a doua dupa ce se
    schimba ceva la ei.
    """
    proposal, account = _client_proposal(proposal_id, client_user, session)
    if proposal.status is not ChangeStatus.PENDING:
        # Verificat si de motor. Aici, ca mesajul sa fie despre STARE - altfel
        # o propunere deja executata ar primi raspunsul despre provider lipsa.
        raise HTTPException(
            status_code=409,
            detail=(
                "doar propunerile in asteptare se pot aproba "
                f"(aceasta e '{proposal.status.value}')"
            ),
        )
    _check_spend_limit(session, account, proposal)

    try:
        target = resolve_target(proposal)
    except NoExecutorError as exc:
        # Propunerea ramane PENDING: nu platforma a refuzat, ci noi nu stim
        # sa aplicam tipul asta. A o marca FAILED ar sugera ca s-a incercat.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    provider = _require_mutation_provider(account, target)

    # Rezervarea: PENDING -> APPROVED atomic, INAINTE de primul apel catre Meta.
    # Din doua cereri simultane, exact una trece de aici.
    if not _transition(session, proposal, frm=ChangeStatus.PENDING, to=ChangeStatus.APPROVED):
        raise _already_decided("aplic")
    try:
        # Rezervarea e acum vizibila celorlalte aprobari: plafonul se re-verifica
        # impreuna cu ele (``spend_guard`` numara si propunerile APPROVED).
        check_spend_limit(
            session, account, proposal.projected_daily_spend, exclude_id=proposal.id
        )
        result = run_execution(proposal, provider, current_status=ChangeStatus.PENDING.value)
    except (SpendLimitExceeded, ProposalNotExecutableError, NoExecutorError) as exc:
        # Nimic n-a plecat spre platforma: rezervarea se elibereaza.
        _transition(session, proposal, frm=ChangeStatus.APPROVED, to=ChangeStatus.PENDING)
        if isinstance(exc, SpendLimitExceeded):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        # Nu stim daca platforma a aplicat schimbarea: FAILED, nu PENDING - o
        # reincercare oarba ar putea-o dubla.
        proposal.status = ChangeStatus.FAILED
        proposal.error_message = (
            f"executia s-a intrerupt ({type(exc).__name__}) - verifica in platforma daca "
            "schimbarea s-a aplicat"
        )
        proposal.decided_at = datetime.now(tz=UTC)
        proposal.decided_by = client_user.email
        session.add(proposal)
        session.commit()
        raise

    decided_at = datetime.now(tz=UTC)
    if result.executed:
        proposal.status = ChangeStatus.EXECUTED
        proposal.error_message = None
    else:
        proposal.status = ChangeStatus.FAILED
        proposal.error_message = result.error
    # La o lansare: id-urile create - sau campania ramasa dupa un rollback esuat.
    proposal.execution_result = result.created or None
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
    if not _transition(session, proposal, frm=ChangeStatus.PENDING, to=ChangeStatus.REJECTED):
        raise _already_decided("resping")
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
    if proposal.status is not ChangeStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=(
                "doar propunerile in asteptare se pot executa "
                f"(aceasta e '{proposal.status.value}')"
            ),
        )
    # Aceeasi rezervare atomica ca la aprobarea clientului.
    if not _transition(session, proposal, frm=ChangeStatus.PENDING, to=ChangeStatus.APPROVED):
        raise _already_decided("execut")

    # Verifica angajamentul TOTAL (propunerile executate sau in curs ale
    # clientului + aceasta), nu doar randul curent — altfel N aprobari
    # individuale, fiecare sub plafon, ar putea depasi impreuna plafonul
    # absolut. Echivalentul per-propunere al verificarii pe intregul changeset
    # din ApprovalGate.flush() (CLI).
    try:
        check_spend_limit(
            session, account, proposal.projected_daily_spend, exclude_id=proposal.id
        )
    except SpendLimitExceeded:
        _transition(session, proposal, frm=ChangeStatus.APPROVED, to=ChangeStatus.PENDING)
        raise

    proposal.status = ChangeStatus.EXECUTED
    proposal.decided_at = datetime.now(tz=UTC)
    proposal.decided_by = tenant.name
    # Nicio platforma nu a fost atinsa. Marcajul e singurul mod in care un
    # raport ulterior (services/reporting) poate deosebi asta de o schimbare
    # reala - altfel clientul ar citi "aplicat" despre ceva ce nu s-a intamplat.
    proposal.execution_result = {"simulated": True}
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
