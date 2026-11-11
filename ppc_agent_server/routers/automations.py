"""Customer-owned native workflows and separately authenticated incoming events."""

from __future__ import annotations

import hashlib
import secrets
from contextlib import suppress
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError
from sqlalchemy import update
from sqlmodel import Session, col, select

from ppc_agent_server.automations.catalog import catalog
from ppc_agent_server.automations.delivery import deliver_message, email_ready
from ppc_agent_server.automations.planner import build_plan
from ppc_agent_server.automations.schemas import Configuration, Event, WorkflowId
from ppc_agent_server.automations.service import (
    AutomationConflict,
    approve_message,
    binding,
    configuration,
    configure,
    persisted_id,
    run_automation_job,
    schedule_due,
    submit,
    update_record,
)
from ppc_agent_server.db import get_session
from ppc_agent_server.jobs.queue import get_job_queue
from ppc_agent_server.models import (
    ClientUser,
    NativeAutomation,
    NativeAutomationMessage,
    NativeAutomationRecord,
    NativeAutomationRun,
)
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.settings import get_server_settings

router = APIRouter(tags=["native-automations"])
User = Annotated[ClientUser, Depends(get_current_client_user)]
DB = Annotated[Session, Depends(get_session)]
BASE = "/api/v1/me/automations"


OwnedRow = TypeVar("OwnedRow", NativeAutomationMessage, NativeAutomationRecord, NativeAutomationRun)


def owned(session: Session, model: type[OwnedRow], row_id: int, account: int) -> OwnedRow:
    row = session.get(model, row_id)
    if not row or row.client_account_id != account:
        raise HTTPException(404, "Înregistrare indisponibilă.")
    return row


def problem(exc: ValueError) -> HTTPException:
    return HTTPException(
        409 if isinstance(exc, AutomationConflict) else 422,
        "Datele formularului nu sunt valide. Verifică câmpurile."
        if isinstance(exc, ValidationError)
        else str(exc),
    )


def enqueue_run(run_id: int) -> None:
    # Durable queued row remains visible if Redis is temporarily unavailable.
    with suppress(Exception):
        get_job_queue().enqueue(run_automation_job, run_id=run_id)


def public_binding(session: Session, account: int, slug: str) -> dict[str, Any]:
    row = binding(session, account, slug)
    url = (
        f"{get_server_settings().public_api_url.rstrip('/')}/api/v1/automation-hooks/{row.id}"
        if row
        else None
    )
    return {
        "config": configuration(session, account, slug).model_dump(mode="json"),
        "webhook_url": url,
        "webhook_key_set": bool(row and row.webhook_hash),
    }


@router.get(BASE)
def overview(user: User, session: DB) -> dict[str, Any]:
    account = user.client_account_id
    return {
        "email_ready": email_ready(),
        "workflows": [
            {**entry, **public_binding(session, account, entry["id"])} for entry in catalog()
        ],
        "runs": session.exec(
            select(NativeAutomationRun)
            .where(col(NativeAutomationRun.client_account_id) == account)
            .order_by(col(NativeAutomationRun.id).desc())
            .limit(50)
        ).all(),
        "messages": [
            {**message.model_dump(mode="json"), "workflow": workflow}
            for message, workflow in session.exec(
                select(NativeAutomationMessage, col(NativeAutomationRun.workflow))
                .join(
                    NativeAutomationRun,
                    col(NativeAutomationMessage.run_id) == col(NativeAutomationRun.id),
                )
                .where(col(NativeAutomationMessage.client_account_id) == account)
                .order_by(col(NativeAutomationMessage.id).desc())
                .limit(100)
            ).all()
        ],
        "records": session.exec(
            select(NativeAutomationRecord)
            .where(col(NativeAutomationRecord.client_account_id) == account)
            .order_by(col(NativeAutomationRecord.id).desc())
            .limit(100)
        ).all(),
    }


@router.put(BASE + "/{slug}/settings")
def save_settings(slug: WorkflowId, data: Configuration, user: User, session: DB) -> dict[str, Any]:
    try:
        configure(session, user.client_account_id, slug, data)
    except ValueError as exc:
        raise problem(exc) from exc
    return public_binding(session, user.client_account_id, slug)


@router.post(BASE + "/{slug}/preview")
def preview(slug: WorkflowId, event: Event, user: User, session: DB) -> dict[str, Any]:
    try:
        # No email, DB mutations or AI charge during a preview.
        return build_plan(
            slug, event.data, configuration(session, user.client_account_id, slug), allow_ai=False
        ).model_dump(mode="json")
    except ValueError as exc:
        raise problem(exc) from exc


@router.post(BASE + "/{slug}/events", status_code=202)
def receive(slug: WorkflowId, event: Event, user: User, session: DB) -> dict[str, Any]:
    try:
        run, duplicate = submit(session, user.client_account_id, slug, event)
    except ValueError as exc:
        raise problem(exc) from exc
    if not duplicate:
        enqueue_run(persisted_id(run.id))
    session.refresh(run)
    return {"run_id": run.id, "status": run.status, "duplicate": duplicate}


@router.put(BASE + "/records/{record_id}")
def edit_record(record_id: int, data: dict[str, Any], user: User, session: DB) -> dict[str, Any]:
    record = owned(session, NativeAutomationRecord, record_id, user.client_account_id)
    try:
        update_record(session, record, data)
    except ValueError as exc:
        raise problem(exc) from exc
    return {"status": "updated"}


@router.post(BASE + "/check-due")
def check_due(user: User, session: DB) -> dict[str, Any]:
    count = schedule_due(session, account=user.client_account_id)
    rows = session.exec(
        select(col(NativeAutomationRun.id))
        .where(
            col(NativeAutomationRun.client_account_id) == user.client_account_id,
            col(NativeAutomationRun.status) == "queued",
        )
        .limit(25)
    ).all()
    for run_id in rows:
        enqueue_run(persisted_id(run_id))
    return {"scheduled": count}


@router.post(BASE + "/runs/{run_id}/retry")
def retry(run_id: int, user: User, session: DB) -> dict[str, Any]:
    run = owned(session, NativeAutomationRun, run_id, user.client_account_id)
    if session.exec(
        select(col(NativeAutomationMessage.id)).where(col(NativeAutomationMessage.run_id) == run_id)
    ).first():
        raise HTTPException(409, "Rularea are deja mesaje. Gestionează-le individual.")
    changed = session.exec(
        update(NativeAutomationRun)
        .where(
            col(NativeAutomationRun.id) == run_id,
            col(NativeAutomationRun.status) == "failed",
        )
        .values(status="queued", error=None, started_at=None, finished_at=None, attempt_token=None)
    )
    session.commit()
    if not changed.rowcount:
        raise HTTPException(409, "Doar o rulare eșuată poate fi reîncercată.")
    enqueue_run(persisted_id(run.id))
    return {"status": "queued"}


@router.post(BASE + "/messages/{message_id}/approve")
def approve(message_id: int, user: User, session: DB) -> dict[str, Any]:
    message = owned(session, NativeAutomationMessage, message_id, user.client_account_id)
    try:
        approve_message(session, message, user)
    except ValueError as exc:
        raise problem(exc) from exc
    # The persisted approved message remains available to the native worker.
    with suppress(Exception):
        get_job_queue().enqueue(deliver_message, message_id=message_id)
    session.refresh(message)
    return {"status": message.status}


@router.post(BASE + "/messages/{message_id}/cancel")
def cancel(message_id: int, user: User, session: DB) -> dict[str, Any]:
    owned(session, NativeAutomationMessage, message_id, user.client_account_id)
    changed = session.exec(
        update(NativeAutomationMessage)
        .where(
            col(NativeAutomationMessage.id) == message_id,
            col(NativeAutomationMessage.status).in_(["pending", "ready", "blocked"]),
        )
        .values(status="cancelled")
    )
    session.commit()
    if not changed.rowcount:
        raise HTTPException(409, "Mesajul a fost deja trimis, anulat sau este în curs de livrare.")
    return {"status": "cancelled"}


@router.post(BASE + "/{slug}/webhook-key")
def new_webhook_key(slug: WorkflowId, user: User, session: DB) -> dict[str, Any]:
    row = binding(session, user.client_account_id, slug)
    if not row:
        row = configure(
            session,
            user.client_account_id,
            slug,
            configuration(session, user.client_account_id, slug),
        )
    key = "auto_" + secrets.token_urlsafe(32)
    row.webhook_hash = hashlib.sha256(key.encode()).hexdigest()
    session.add(row)
    session.commit()
    return {**public_binding(session, user.client_account_id, slug), "key": key}


@router.delete(BASE + "/{slug}/webhook-key")
def revoke_webhook_key(slug: WorkflowId, user: User, session: DB) -> dict[str, Any]:
    row = binding(session, user.client_account_id, slug)
    if row:
        row.webhook_hash = None
        session.add(row)
        session.commit()
    return {"status": "revoked"}


@router.post("/api/v1/automation-hooks/{hook_id}", status_code=202)
def webhook(
    hook_id: int, event: Event, session: DB, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    row = session.get(NativeAutomation, hook_id)
    key = (
        authorization.removeprefix("Bearer ")
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    digest = hashlib.sha256(key.encode()).hexdigest()
    if (
        not row
        or not row.webhook_hash
        or not key
        or not secrets.compare_digest(row.webhook_hash, digest)
    ):
        raise HTTPException(401, "Cheie de webhook invalidă.")
    try:
        run, duplicate = submit(session, row.client_account_id, row.workflow, event)
    except ValueError as exc:
        raise problem(exc) from exc
    if not duplicate:
        enqueue_run(persisted_id(run.id))
    return {"run_id": run.id, "duplicate": duplicate}
