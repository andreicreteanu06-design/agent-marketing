"""``POST /api/v1/jobs/{plan,copy,creative}`` + ``GET /api/v1/jobs/{task_id}``.

Fiecare ``POST`` valideaza ca ``client_id`` apartine agentiei autentificate
*sincron, in router*, inainte de ``queue.enqueue(...)`` — cu ``ArqJobQueue``
(Faza F), task-ul ruleaza intr-un proces worker separat, fara nicio sesiune
HTTP; erorile de forma cererii ("client gresit") trebuie rezolvate aici, nu
in interiorul job-ului.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.deps import get_owned_client
from ppc_agent_server.jobs.queue import JobQueue, get_job_queue
from ppc_agent_server.jobs.tasks import run_copy_job, run_creative_job, run_plan_job
from ppc_agent_server.models import Tenant
from ppc_agent_server.schemas import (
    CopyJobRequest,
    CreativeJobRequest,
    JobAccepted,
    JobStatusResponse,
    PlanJobRequest,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _accepted(queue: JobQueue, task_id: str) -> JobAccepted:
    """Starea reala imediat dupa ``enqueue`` — cu ``InlineJobQueue`` jobul s-a
    terminat deja (``success``/``failed``), nu ramane niciodata ``queued``."""
    result = queue.status(task_id)
    return JobAccepted(task_id=task_id, status=result.status if result else "queued")


@router.post("/plan", response_model=JobAccepted, status_code=202)
def dispatch_plan(
    payload: PlanJobRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobAccepted:
    """Dispecerizeaza Modulul 2 (Kelly + Thompson + Markov) pentru un client."""
    get_owned_client(payload.client_id, tenant, session)
    task_id = queue.enqueue("plan", run_plan_job, client_account_id=payload.client_id)
    return _accepted(queue, task_id)


@router.post("/copy", response_model=JobAccepted, status_code=202)
def dispatch_copy(
    payload: CopyJobRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobAccepted:
    """Dispecerizeaza generarea de copy emotional (mock sau Ollama live)."""
    get_owned_client(payload.client_id, tenant, session)
    task_id = queue.enqueue(
        "copy",
        run_copy_job,
        client_account_id=payload.client_id,
        keyword=payload.keyword,
        usp=payload.usp,
        trigger=payload.trigger,
        platform=payload.platform,
    )
    return _accepted(queue, task_id)


@router.post("/creative", response_model=JobAccepted, status_code=202)
def dispatch_creative(
    payload: CreativeJobRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobAccepted:
    """Dispecerizeaza Modulul 5 (voce + video)."""
    get_owned_client(payload.client_id, tenant, session)
    task_id = queue.enqueue(
        "creative",
        run_creative_job,
        client_account_id=payload.client_id,
        keyword=payload.keyword,
        broll_path=payload.broll_path,
        trigger=payload.trigger,
        usp=payload.usp,
        platform=payload.platform,
    )
    return _accepted(queue, task_id)


@router.get("/{task_id}", response_model=JobStatusResponse)
def get_job_status(
    task_id: str,
    _tenant: Annotated[Tenant, Depends(get_current_tenant)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobStatusResponse:
    """Starea unui job dispecerizat anterior.

    Nu verifica apartenenta de tenant (``task_id``-ul e un UUID neghicibil,
    nu o resursa enumerabila) — orice agentie autentificata cu un task_id
    valid ii poate vedea starea, la fel cum un link de tracking nu cere
    reautentificare pe fiecare pas.
    """
    result = queue.status(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task_id necunoscut")
    return JobStatusResponse(
        task_id=result.task_id, status=result.status, result=result.result, error=result.error
    )
