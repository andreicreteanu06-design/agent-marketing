"""SMTP outbox with an atomic claim; ambiguous sends are never retried automatically."""

from __future__ import annotations

import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy import update
from sqlmodel import Session, col

from ppc_agent_server.automations import planner
from ppc_agent_server.automations.catalog import SCHEDULED
from ppc_agent_server.automations.schemas import valid_email
from ppc_agent_server.automations.service import configuration, fingerprint
from ppc_agent_server.db import get_engine
from ppc_agent_server.models import (
    NativeAutomationMessage,
    NativeAutomationRecord,
    NativeAutomationRun,
)
from ppc_agent_server.settings import get_server_settings


def email_ready() -> bool:
    cfg = get_server_settings()
    try:
        valid_email(cfg.automation_smtp_from)
    except ValueError:
        return False
    return bool(
        cfg.automation_email_enabled
        and cfg.automation_smtp_host
        and (not cfg.automation_smtp_username or cfg.automation_smtp_password)
    )


def send_smtp(message: NativeAutomationMessage) -> None:
    cfg = get_server_settings()
    email = EmailMessage()
    email["From"] = valid_email(cfg.automation_smtp_from)
    email["To"] = valid_email(message.recipient)
    email["Subject"] = message.subject
    domain = cfg.automation_smtp_from.rsplit("@", 1)[-1]
    email["Message-ID"] = f"<ac-automation-{message.id}@{domain}>"
    email.set_content(message.body)
    transport: smtplib.SMTP
    if cfg.automation_smtp_ssl:
        transport = smtplib.SMTP_SSL(
            cfg.automation_smtp_host,
            cfg.automation_smtp_port,
            timeout=20,
            context=ssl.create_default_context(),
        )
    else:
        transport = smtplib.SMTP(cfg.automation_smtp_host, cfg.automation_smtp_port, timeout=20)
    with transport as server:
        if not cfg.automation_smtp_ssl:
            server.starttls(context=ssl.create_default_context())
        if cfg.automation_smtp_username:
            server.login(cfg.automation_smtp_username, cfg.automation_smtp_password)
        refused = server.send_message(email)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def deliver_message(*, message_id: int) -> dict[str, str]:
    with Session(get_engine()) as session:
        message = session.get(NativeAutomationMessage, message_id)
        if not message or message.status != "ready":
            return {"status": "not_ready"}
        run = session.get(NativeAutomationRun, message.run_id)
        if run is None:
            return {"status": "not_found"}
        cfg = configuration(session, message.client_account_id, run.workflow)
        if not cfg.enabled:
            return {"status": "paused"}
        record = session.get(NativeAutomationRecord, run.record_id)
        if not record or fingerprint(record.payload) != fingerprint(run.payload):
            session.exec(
                update(NativeAutomationMessage)
                .where(
                    col(NativeAutomationMessage.id) == message_id,
                    col(NativeAutomationMessage.status) == "ready",
                )
                .values(status="cancelled", error="Datele sursă au fost modificate.")
            )
            session.commit()
            return {"status": "cancelled"}
        # Approval can happen days after preparation. Expired reminders must not
        # be sent alongside the new stage, even when the source data is unchanged.
        if run.workflow in SCHEDULED:
            current_plan = planner.build_plan(run.workflow, record.payload, cfg, allow_ai=False)
            if current_plan.skipped or current_plan.stage != run.result.get("stage"):
                session.exec(
                    update(NativeAutomationMessage)
                    .where(
                        col(NativeAutomationMessage.id) == message_id,
                        col(NativeAutomationMessage.status) == "ready",
                    )
                    .values(status="cancelled", error="Etapa mesajului a expirat.")
                )
                session.commit()
                return {"status": "cancelled"}
        if not email_ready():
            session.exec(
                update(NativeAutomationMessage)
                .where(
                    col(NativeAutomationMessage.id) == message_id,
                    col(NativeAutomationMessage.status) == "ready",
                )
                .values(
                    status="blocked",
                    error="Trimiterea SMTP nu este configurată sau activată pe server.",
                )
            )
            session.commit()
            return {"status": "blocked"}
        # Mode can be tightened while an automatic message waits in the outbox.
        if (message.requires_review or cfg.delivery_mode == "review") and not message.approved_by:
            session.exec(
                update(NativeAutomationMessage)
                .where(
                    col(NativeAutomationMessage.id) == message_id,
                    col(NativeAutomationMessage.status) == "ready",
                )
                .values(status="pending", requires_review=True)
            )
            session.commit()
            return {"status": "pending"}
        claim = session.exec(
            update(NativeAutomationMessage)
            .where(
                col(NativeAutomationMessage.id) == message_id,
                col(NativeAutomationMessage.status) == "ready",
            )
            .values(status="sending", sending_at=datetime.now(UTC))
        )
        session.commit()
        if not claim.rowcount:
            return {"status": "already_claimed"}
        session.refresh(message)
        try:
            send_smtp(message)
        except Exception:
            message.status = "uncertain"
            message.error = (
                "Serverul de email nu a confirmat livrarea. "
                "Verifică mesajele trimise; nu reluăm automat."
            )
        else:
            message.status = "sent"
            message.sent_at = datetime.now(UTC)
            message.error = None
        session.add(message)
        session.commit()
        return {"status": message.status}
