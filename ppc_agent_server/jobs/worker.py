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
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.worker import Function, func

from ppc_agent_server.jobs.tasks import (
    AdPlatform,
    run_copy_job,
    run_creative_job,
    run_daily_maintenance_job,
    run_fatigue_check_job,
    run_metrics_sync_job,
    run_plan_job,
    run_propose_job,
)
from ppc_agent_server.settings import get_server_settings

_DEFAULT_REDIS_URL = "redis://localhost:6379"
_DAILY_MAINTENANCE_HOUR = 3
"""03:00 - fereastra tipica de mentenanta in afara orelor de varf de trafic."""


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


async def _daily_maintenance_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Wrapper pentru cron - sincronizare + propuneri + oboseala, pentru toti clientii.

    Doar genereaza propuneri ``pending`` (vezi ``run_daily_maintenance_job``) -
    nimic nu se executa automat. Ruleaza doar cand un worker ARQ real e pornit
    impotriva unui Redis real (``REDIS_URL`` setat) - la fel ca restul cozii
    ``arq``, netestat impotriva unui Redis real in acest mediu (vezi nota
    epistemica din ``arq_queue.py``); ``run_daily_maintenance_job`` in sine e
    testat direct, fara Redis/ARQ, ca toate celelalte functii din ``tasks.py``.
    """
    return await asyncio.to_thread(run_daily_maintenance_job)


class WorkerSettings:
    """Configuratia consumata de comanda ``arq``. Clasa nu e instantiata
    niciodata — ``arq`` ii citeste atributele direct (patternul documentat
    al bibliotecii), de-asta sunt ``ClassVar``, nu campuri de instanta."""

    functions: ClassVar[list[Function]] = [
        func(_plan_task, name=run_plan_job.__name__),
        func(_copy_task, name=run_copy_job.__name__),
        func(_creative_task, name=run_creative_job.__name__),
        func(_propose_task, name=run_propose_job.__name__),
        func(_fatigue_check_task, name=run_fatigue_check_job.__name__),
        func(_sync_metrics_task, name=run_metrics_sync_job.__name__),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(
            _daily_maintenance_task,
            name="daily_maintenance",
            hour={_DAILY_MAINTENANCE_HOUR},
            minute={0},
        ),
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(
        get_server_settings().redis_url or _DEFAULT_REDIS_URL
    )
