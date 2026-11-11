"""Worker-ul ARQ: procesul separat care consuma joburi din Redis.

Ruleaza cu::

    arq ppc_agent_server.jobs.worker.WorkerSettings

``arq`` cere ca fiecare functie inregistrata sa accepte ``ctx`` (contextul
worker-ului) ca prim argument (``function.coroutine(ctx, *args, **kwargs)`` in
``arq.worker.Worker.run_job``) — de-asta acestea sunt wrapper-e subtiri peste
functiile pure din ``jobs/tasks.py``, nu acele functii direct (care raman
neschimbate, agnostice de coada, testate deja in Faza E). Fiecare wrapper e
inregistrat cu ``name=`` explicit egal cu numele functiei originale din
``tasks.py`` — acelasi nume pe care ``ArqJobQueue.enqueue`` il deriva din
``func.__name__`` la dispecerizare, ca sa nu poata diverge niciodata.

``asyncio.to_thread``: munca reala (provideri mock/live, baza de date) e
sincrona si poate dura — rulata intr-un fir separat, nu blocheaza bucla de
evenimente a worker-ului (care poate procesa alte job-uri concurent).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.worker import Function, func

from ppc_agent_server.automations.delivery import deliver_message
from ppc_agent_server.automations.service import run_automation_job
from ppc_agent_server.automations.worker import run_native_tick
from ppc_agent_server.jobs.tasks import (
    AdPlatform,
    list_client_account_ids,
    run_client_maintenance_job,
    run_copy_job,
    run_creative_job,
    run_fatigue_check_job,
    run_metrics_sync_job,
    run_plan_job,
    run_propose_job,
)
from ppc_agent_server.jobs.weekly_report import run_weekly_reports_job
from ppc_agent_server.settings import get_server_settings

_DEFAULT_REDIS_URL = "redis://localhost:6379"
_DAILY_MAINTENANCE_HOUR = 3
"""03:00 - fereastra tipica de mentenanta in afara orelor de varf de trafic."""
_WEEKLY_REPORT_WEEKDAY = 0
"""Luni (``datetime.weekday()``): raportul acopera saptamana care tocmai s-a incheiat."""
_WEEKLY_REPORT_HOUR = 6
"""06:00 - dupa mentenanta de noapte, inainte ca clientul sa-si deschida contul."""
CLIENT_MAINTENANCE_TIMEOUT_SECONDS = 600
"""Cat are voie sa dureze mentenanta UNUI client (sincronizare + propuneri +
oboseala, fiecare cu timeout-urile de 30s ale platformelor). Peste, ARQ marcheaza
jobul esuat - iar ceilalti clienti nu observa nimic."""


async def _plan_task(ctx: dict[str, Any], *, client_account_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(run_plan_job, client_account_id=client_account_id)


async def _copy_task(
    ctx: dict[str, Any],
    *,
    client_account_id: int,
    keyword: str,
    usp: str,
    trigger: str,
    platform: AdPlatform,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        run_copy_job,
        client_account_id=client_account_id,
        keyword=keyword,
        usp=usp,
        trigger=trigger,
        platform=platform,
    )


async def _creative_task(
    ctx: dict[str, Any],
    *,
    client_account_id: int,
    keyword: str,
    broll_path: str,
    trigger: str,
    usp: str | None,
    platform: AdPlatform,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        run_creative_job,
        client_account_id=client_account_id,
        keyword=keyword,
        broll_path=broll_path,
        trigger=trigger,
        usp=usp,
        platform=platform,
    )


async def _propose_task(ctx: dict[str, Any], *, client_account_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(run_propose_job, client_account_id=client_account_id)


async def _fatigue_check_task(ctx: dict[str, Any], *, client_account_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(run_fatigue_check_job, client_account_id=client_account_id)


async def _sync_metrics_task(ctx: dict[str, Any], *, client_account_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(run_metrics_sync_job, client_account_id=client_account_id)


async def _client_maintenance_task(
    ctx: dict[str, Any], *, client_account_id: int
) -> dict[str, Any]:
    return await asyncio.to_thread(
        run_client_maintenance_job, client_account_id=client_account_id
    )


async def _daily_maintenance_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron-ul de noapte: programeaza cate un micro-job per client (fan-out).

    Nu mai face munca intr-un singur job mare: acela avea UN timeout pentru toti
    clientii, iar un client lent ii intarzia pe toti ceilalti. Acum fiecare client
    e un job separat, cu timeout-ul lui (``CLIENT_MAINTENANCE_TIMEOUT_SECONDS``),
    procesat in paralel de worker (``max_jobs``). ``_job_id`` contine ziua: daca
    cron-ul porneste de doua ori in aceeasi zi, ARQ nu dubleaza jobul (si deci nici
    propunerile). Doar genereaza propuneri ``pending`` - nimic nu se executa automat.
    """
    client_ids = await asyncio.to_thread(list_client_account_ids)
    day = datetime.now(tz=UTC).date().isoformat()
    enqueued = 0
    for client_id in client_ids:
        job = await ctx["redis"].enqueue_job(
            run_client_maintenance_job.__name__,
            client_account_id=client_id,
            _job_id=f"maintenance:{day}:{client_id}",
        )
        if job is not None:  # None = deja programat azi
            enqueued += 1
    return {"clients": len(client_ids), "enqueued": enqueued}


async def _weekly_reports_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Wrapper pentru cron - raportul saptamanal al fiecarui client activ.

    Aceeasi nota ca la ``_daily_maintenance_task``: ruleaza doar cu un worker
    ARQ real; ``run_weekly_reports_job`` e testat direct, fara Redis.
    """
    return await asyncio.to_thread(run_weekly_reports_job)


async def _native_run_task(ctx: dict[str, Any], *, run_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(run_automation_job, run_id=run_id)


async def _native_email_task(ctx: dict[str, Any], *, message_id: int) -> dict[str, Any]:
    return await asyncio.to_thread(deliver_message, message_id=message_id)


async def _native_tick_task(ctx: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(run_native_tick)


class WorkerSettings:
    """Configuratia consumata de comanda ``arq``. Clasa nu e instantiata
    niciodata — ``arq`` ii citeste atributele direct (patternul documentat
    al bibliotecii), de-asta sunt ``ClassVar``, nu campuri de instanta."""

    functions: ClassVar[list[Function]] = [
        func(_native_run_task, name=run_automation_job.__name__, timeout=1200, max_tries=1),
        func(_native_email_task, name=deliver_message.__name__, timeout=90, max_tries=1),
        func(_plan_task, name=run_plan_job.__name__),
        func(_copy_task, name=run_copy_job.__name__),
        func(_creative_task, name=run_creative_job.__name__),
        func(_propose_task, name=run_propose_job.__name__),
        func(_fatigue_check_task, name=run_fatigue_check_job.__name__),
        func(_sync_metrics_task, name=run_metrics_sync_job.__name__),
        func(
            _client_maintenance_task,
            name=run_client_maintenance_job.__name__,
            timeout=CLIENT_MAINTENANCE_TIMEOUT_SECONDS,
            # O rulare intrerupta nu se reia oarba (ar dubla propunerile) - maine
            # noaptea clientul intra oricum din nou in lista.
            max_tries=1,
        ),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(
            _native_tick_task, name="native_automations",
            minute=set(range(0, 60, 5)), timeout=1200, max_tries=1,
        ),
        cron(
            _daily_maintenance_task,
            name="daily_maintenance",
            hour={_DAILY_MAINTENANCE_HOUR},
            minute={0},
        ),
        cron(
            _weekly_reports_task,
            name="weekly_reports",
            weekday={_WEEKLY_REPORT_WEEKDAY},
            hour={_WEEKLY_REPORT_HOUR},
            minute={0},
        ),
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(
        get_server_settings().redis_url or _DEFAULT_REDIS_URL
    )
