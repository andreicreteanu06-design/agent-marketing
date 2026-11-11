"""Durable native execution, tenant ownership and idempotent outbox planning."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from ppc_agent_server.automations.catalog import SCHEDULED
from ppc_agent_server.automations.planner import build_plan
from ppc_agent_server.automations.schemas import INPUTS, Configuration, Event
from ppc_agent_server.db import get_engine
from ppc_agent_server.models import (
    ClientAccount,
    ClientUser,
    NativeAutomation,
    NativeAutomationMessage,
    NativeAutomationRecord,
    NativeAutomationRun,
)


class AutomationConflict(ValueError):
    pass


def persisted_id(value: int | None) -> int:
    """Require a database-assigned ID before enqueueing or referencing a row."""
    if value is None:
        raise ValueError("Înregistrarea nu a fost salvată.")
    return value


def fingerprint(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def binding(session: Session, account: int, slug: str) -> NativeAutomation | None:
    return session.exec(
        select(NativeAutomation).where(
            col(NativeAutomation.client_account_id) == account,
            col(NativeAutomation.workflow) == slug,
        )
    ).first()


def configuration(session: Session, account: int, slug: str) -> Configuration:
    row = binding(session, account, slug)
    if row:
        return Configuration.model_validate({**row.options, "enabled": row.enabled})
    user = session.exec(select(ClientUser).where(ClientUser.client_account_id == account)).first()
    client = session.get(ClientAccount, account)
    return Configuration(
        team_email=user.email if user else "", company_name=client.name if client else "Compania ta"
    )


def configure(
    session: Session, account: int, slug: str, options: Configuration
) -> NativeAutomation:
    if options.enabled and not options.team_email:
        raise ValueError("Completează emailul echipei înainte de activare.")
    row = binding(session, account, slug)
    if row is None:
        row = NativeAutomation(client_account_id=account, workflow=slug)
    row.enabled = options.enabled
    row.options = options.model_dump(mode="json", exclude={"enabled"})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def submit(
    session: Session, account: int, slug: str, event: Event
) -> tuple[NativeAutomationRun, bool]:
    cfg = configuration(session, account, slug)
    if not cfg.enabled:
        raise AutomationConflict("Activează fluxul înainte de a primi evenimente.")
    data = INPUTS[slug].model_validate(event.data).model_dump(mode="json")
    preview = build_plan(slug, data, cfg, allow_ai=False)
    external = str(data.get("invoice_id") or data.get("order_id") or event.event_id)
    run_key = f"scheduled:{external}:{preview.stage}" if slug in SCHEDULED else f"event:{external}"
    existing = session.exec(
        select(NativeAutomationRun).where(
            col(NativeAutomationRun.client_account_id) == account,
            col(NativeAutomationRun.workflow) == slug,
            col(NativeAutomationRun.run_key) == run_key,
        )
    ).first()
    if existing:
        if fingerprint(existing.payload) != fingerprint(data):
            raise AutomationConflict(
                "Identificatorul există cu alte date. Actualizează înregistrarea din istoric."
            )
        return existing, True
    record = session.exec(
        select(NativeAutomationRecord).where(
            col(NativeAutomationRecord.client_account_id) == account,
            col(NativeAutomationRecord.workflow) == slug,
            col(NativeAutomationRecord.external_id) == external,
        )
    ).first()
    if record and fingerprint(record.payload) != fingerprint(data):
        raise AutomationConflict(
            "Înregistrarea există. Folosește actualizarea ei pentru modificări."
        )
    try:
        if record is None:
            record = NativeAutomationRecord(
                client_account_id=account, workflow=slug, external_id=external, payload=data
            )
            session.add(record)
            session.flush()
        run = NativeAutomationRun(
            client_account_id=account,
            workflow=slug,
            record_id=persisted_id(record.id),
            run_key=run_key,
            payload=data,
        )
        session.add(run)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(NativeAutomationRun).where(
                col(NativeAutomationRun.client_account_id) == account,
                col(NativeAutomationRun.workflow) == slug,
                col(NativeAutomationRun.run_key) == run_key,
            )
        ).first()
        if existing and fingerprint(existing.payload) == fingerprint(data):
            return existing, True
        raise AutomationConflict(
            "Eveniment concurent. Reîncearcă folosind același identificator."
        ) from None
    session.refresh(run)
    return run, False


def update_record(session: Session, row: NativeAutomationRecord, data: dict[str, Any]) -> None:
    parsed = INPUTS[row.workflow].model_validate(data).model_dump(mode="json")
    for key in ("invoice_id", "order_id"):
        if key in row.payload and parsed.get(key) != row.payload[key]:
            raise ValueError("Numărul facturii/comenzii nu poate fi schimbat după înregistrare.")
    if fingerprint(parsed) == fingerprint(row.payload):
        return
    row.payload = parsed
    row.updated_at = datetime.now(UTC)
    session.add(row)
    # A previously approved draft cannot silently change with its source record.
    run_ids = select(col(NativeAutomationRun.id)).where(
        col(NativeAutomationRun.record_id) == row.id
    )
    session.exec(
        update(NativeAutomationMessage)
        .where(
            col(NativeAutomationMessage.run_id).in_(run_ids),
            col(NativeAutomationMessage.status).in_(["pending", "ready", "blocked"]),
        )
        .values(
            status="cancelled",
            error="Datele sursă au fost actualizate; ciorna veche a fost anulată.",
        )
    )
    session.commit()


def run_automation_job(*, run_id: int) -> dict[str, Any]:
    attempt = str(uuid.uuid4())
    with Session(get_engine()) as session:
        claimed = session.exec(
            update(NativeAutomationRun)
            .where(
                col(NativeAutomationRun.id) == run_id,
                col(NativeAutomationRun.status) == "queued",
            )
            .values(status="running", started_at=datetime.now(UTC), attempt_token=attempt)
        )
        session.commit()
        if not claimed.rowcount:
            return {"status": "already_claimed", "run_id": run_id}
        run = session.get(NativeAutomationRun, run_id)
        if run is None:
            return {"status": "not_found", "run_id": run_id}
        try:
            cfg = configuration(session, run.client_account_id, run.workflow)
            record = session.get(NativeAutomationRecord, run.record_id)
            if not cfg.enabled:
                raise AutomationConflict("Fluxul a fost pus pe pauză.")
            if not record or fingerprint(record.payload) != fingerprint(run.payload):
                raise AutomationConflict("Datele au fost actualizate. Rularea veche a fost oprită.")
            plan = build_plan(run.workflow, run.payload, cfg)
            # A delayed job must never execute a new stage under an older stage's key.
            # The scheduler creates the current stage separately, with its own unique key.
            if run.workflow in SCHEDULED and run.run_key.rsplit(":", 1)[-1] != plan.stage:
                plan = plan.model_copy(
                    update={
                        "stage": run.run_key.rsplit(":", 1)[-1],
                        "skipped": True,
                        "messages": [],
                        "summary": "Etapa a expirat; se verifică etapa curentă.",
                    }
                )
            # Recheck after a potentially slow AI call. Fresh reads avoid stale identity-map data.
            session.expire_all()
            if run is None or run.status != "running" or run.attempt_token != attempt:
                return {"status": "superseded", "run_id": run_id}
            current = binding(session, run.client_account_id, run.workflow)
            record = session.get(NativeAutomationRecord, run.record_id)
            if (
                not current
                or not current.enabled
                or record is None
                or fingerprint(record.payload) != fingerprint(run.payload)
            ):
                raise AutomationConflict("Fluxul sau datele s-au schimbat în timpul pregătirii.")
            cfg = configuration(session, run.client_account_id, run.workflow)
            for i, draft in enumerate(plan.messages):
                review = cfg.delivery_mode == "review" or draft.requires_review
                session.add(
                    NativeAutomationMessage(
                        client_account_id=run.client_account_id,
                        run_id=run_id,
                        step=i,
                        recipient=draft.recipient,
                        subject=draft.subject,
                        body=draft.body,
                        requires_review=review,
                        status="pending" if review else "ready",
                    )
                )
            run.result = plan.model_dump(mode="json", exclude={"messages"})
            run.status = "skipped" if plan.skipped else "prepared"
            run.finished_at = datetime.now(UTC)
            session.add(run)
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(NativeAutomationRun, run_id)
            if run is None or run.status != "running" or run.attempt_token != attempt:
                return {"status": "superseded", "run_id": run_id}
            run.status = "failed"
            run.error = (
                str(exc)[:300]
                if isinstance(exc, (ValueError, AutomationConflict))
                else "Pregătirea a eșuat. Reîncearcă din istoric."
            )
            run.finished_at = datetime.now(UTC)
            session.add(run)
            session.commit()
        return {"run_id": run_id, "status": run.status}


def approve_message(session: Session, message: NativeAutomationMessage, user: ClientUser) -> None:
    if message.client_account_id != user.client_account_id:
        raise AutomationConflict("Mesaj indisponibil.")
    run = session.get(NativeAutomationRun, message.run_id)
    if run is None:
        raise AutomationConflict("Rularea mesajului nu mai este disponibilă.")
    if not configuration(session, user.client_account_id, run.workflow).enabled:
        raise AutomationConflict("Fluxul este pe pauză.")
    claimed = session.exec(
        update(NativeAutomationMessage)
        .where(
            col(NativeAutomationMessage.id) == message.id,
            col(NativeAutomationMessage.status).in_(["pending", "blocked"]),
        )
        .values(status="ready", approved_by=user.id, approved_at=datetime.now(UTC), error=None)
    )
    if not claimed.rowcount:
        session.rollback()
        raise AutomationConflict("Mesajul nu mai așteaptă aprobarea sau are livrare incertă.")
    session.commit()


def schedule_due(session: Session, *, account: int | None = None) -> int:
    query = select(NativeAutomation).where(col(NativeAutomation.enabled) == True)  # noqa: E712
    if account is not None:
        query = query.where(col(NativeAutomation.client_account_id) == account)
    configs = session.exec(query).all()
    count = 0
    for config in configs:
        if config.workflow not in SCHEDULED:
            continue
        cfg = configuration(session, config.client_account_id, config.workflow)
        records = session.exec(
            select(NativeAutomationRecord).where(
                col(NativeAutomationRecord.client_account_id) == config.client_account_id,
                col(NativeAutomationRecord.workflow) == config.workflow,
            )
        ).all()
        for record in records:
            plan = build_plan(record.workflow, record.payload, cfg, allow_ai=False)
            if plan.skipped:
                continue
            key = f"scheduled:{record.external_id}:{plan.stage}"
            exists = session.exec(
                select(col(NativeAutomationRun.id)).where(
                    col(NativeAutomationRun.client_account_id) == config.client_account_id,
                    col(NativeAutomationRun.workflow) == config.workflow,
                    col(NativeAutomationRun.run_key) == key,
                )
            ).first()
            if exists is not None:
                continue
            session.add(
                NativeAutomationRun(
                    client_account_id=config.client_account_id,
                    workflow=config.workflow,
                    record_id=persisted_id(record.id),
                    run_key=key,
                    payload=record.payload,
                )
            )
            try:
                session.commit()
                count += 1
            except IntegrityError:
                session.rollback()  # Another scheduler already inserted this stage.
    return count


def recover_interrupted(session: Session) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=30)
    session.exec(
        update(NativeAutomationRun)
        .where(
            col(NativeAutomationRun.status) == "running",
            col(NativeAutomationRun.started_at) < cutoff,
        )
        .values(status="failed", error="Workerul a fost întrerupt. Rularea poate fi reîncercată.")
    )
    session.exec(
        update(NativeAutomationMessage)
        .where(
            col(NativeAutomationMessage.status) == "sending",
            col(NativeAutomationMessage.sending_at) < cutoff,
        )
        .values(
            status="uncertain",
            error="Livrare întreruptă. Verifică emailul trimis înainte de orice retrimitere.",
        )
    )
    session.commit()
