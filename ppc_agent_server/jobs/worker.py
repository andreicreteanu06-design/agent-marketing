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

from arq.connections import RedisSettings
from arq.worker import Function, func

from ppc_agent_server.jobs.tasks import AdPlatform, run_copy_job, run_creative_job, run_plan_job
from ppc_agent_server.settings import get_server_settings

_DEFAULT_REDIS_URL = "redis://localhost:6379"


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


class WorkerSettings:
    """Configuratia consumata de comanda ``arq``. Clasa nu e instantiata
    niciodata — ``arq`` ii citeste atributele direct (patternul documentat
    al bibliotecii), de-asta sunt ``ClassVar``, nu campuri de instanta."""

    functions: ClassVar[list[Function]] = [
        func(_plan_task, name=run_plan_job.__name__),
        func(_copy_task, name=run_copy_job.__name__),
        func(_creative_task, name=run_creative_job.__name__),
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(
        get_server_settings().redis_url or _DEFAULT_REDIS_URL
    )
