"""Optional standalone worker: python -m ppc_agent_server.automations.worker [--once]."""

from __future__ import annotations

import argparse
import logging
import time

from sqlmodel import Session, col, select

from ppc_agent_server.automations.delivery import deliver_message
from ppc_agent_server.automations.service import (
    persisted_id,
    recover_interrupted,
    run_automation_job,
    schedule_due,
)
from ppc_agent_server.db import get_engine, init_db
from ppc_agent_server.models import NativeAutomation, NativeAutomationMessage, NativeAutomationRun

logger = logging.getLogger(__name__)


def run_native_tick() -> dict[str, int]:
    with Session(get_engine()) as session:
        recover_interrupted(session)
        scheduled = schedule_due(session)
        run_ids = list(
            session.exec(
                select(col(NativeAutomationRun.id))
                .where(
                    col(NativeAutomationRun.status) == "queued",
                )
                .order_by(col(NativeAutomationRun.id))
                .limit(25)
            ).all()
        )
    for run_id in run_ids:
        run_automation_job(run_id=persisted_id(run_id))
    with Session(get_engine()) as session:
        message_ids = list(
            session.exec(
                select(col(NativeAutomationMessage.id))
                .join(
                    NativeAutomationRun,
                    col(NativeAutomationMessage.run_id) == col(NativeAutomationRun.id),
                )
                .join(
                    NativeAutomation,
                    (
                        col(NativeAutomation.client_account_id)
                        == col(NativeAutomationRun.client_account_id)
                    )
                    & (col(NativeAutomation.workflow) == col(NativeAutomationRun.workflow)),
                )
                .where(col(NativeAutomation.enabled) == True)  # noqa: E712
                .where(
                    col(NativeAutomationMessage.status) == "ready",
                )
                .order_by(col(NativeAutomationMessage.id))
                .limit(100)
            ).all()
        )
    for message_id in message_ids:
        deliver_message(message_id=persisted_id(message_id))
    return {
        "scheduled": scheduled,
        "runs_checked": len(run_ids),
        "messages_checked": len(message_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker pentru cele nouă automatizări native")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    init_db()
    while True:
        try:
            run_native_tick()
        except Exception:
            logger.exception("Verificarea automatizărilor a eșuat; se reia la următorul ciclu.")
            if args.once:
                raise
        if args.once:
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
