"""``ArqJobQueue`` — coada reala prin Redis, cu exact contractul :class:`JobQueue`.

Bridge sincron -> async: protocolul ``JobQueue`` e sincron (potrivit pentru
router-e FastAPI definite cu ``def``, rulate automat de FastAPI intr-un
threadpool), dar API-ul ``arq`` e integral async. Fiecare metoda publica
deschide un event loop scurt (``asyncio.run``) — sigur dintr-un worker de
threadpool, care nu are alt loop activ pe acel fir.

Poolul de conexiuni Redis e lazy: construirea acestei clase NU cere Redis
pornit — doar prima folosire efectiva (``enqueue``/``status``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus
from arq.jobs import JobResult as ArqJobResult

from ppc_agent_server.jobs.queue import JobResult


def _map_status(task_id: str, arq_status: JobStatus) -> JobResult | None:
    """Traduce un :class:`arq.jobs.JobStatus` brut, fara rezultat inca disponibil.

    Functie pura, testabila fara Redis — nu acopera ``complete`` (are nevoie de
    ``result_info()``, vezi :func:`_map_result`).
    """
    if arq_status == JobStatus.not_found:
        return None
    if arq_status in (JobStatus.deferred, JobStatus.queued):
        return JobResult(task_id=task_id, status="queued", created_at=datetime.now(tz=UTC))
    if arq_status == JobStatus.in_progress:
        return JobResult(task_id=task_id, status="running", created_at=datetime.now(tz=UTC))
    return None  # JobStatus.complete - apelantul trece la _map_result


def _map_result(task_id: str, info: ArqJobResult | None) -> JobResult:
    """Traduce un :class:`arq.jobs.JobResult` (job terminat) — functie pura, testabila."""
    if info is None:
        # statusul arata 'complete' dar rezultatul nu s-a scris inca - tranzitoriu
        return JobResult(task_id=task_id, status="running", created_at=datetime.now(tz=UTC))
    return JobResult(
        task_id=task_id,
        status="success" if info.success else "failed",
        result=info.result if info.success else None,
        error=None if info.success else str(info.result),
        created_at=info.enqueue_time,
        finished_at=info.finish_time,
    )


class ArqJobQueue:
    """Coada reala prin Redis — acelasi contract ca :class:`InlineJobQueue`."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        return self._pool

    def enqueue(self, func: Callable[..., dict[str, Any]], /, **kwargs: Any) -> str:
        """Dispecerizeaza catre worker-ul ARQ (``jobs/worker.py``).

        Numele job-ului trimis prin Redis e ``func.__name__`` — worker-ul
        inregistreaza wrapper-ele lui async sub acelasi nume explicit (vezi
        ``func(..., name=...)`` in ``WorkerSettings``), ca cele doua sa nu se
        poata dezalinia niciodata.
        """
        return asyncio.run(self._enqueue_async(func.__name__, **kwargs))

    async def _enqueue_async(self, job_name: str, **kwargs: Any) -> str:
        pool = await self._get_pool()
        job = await pool.enqueue_job(job_name, **kwargs)
        if job is None:
            raise RuntimeError(
                f"job-ul '{job_name}' nu a putut fi dispecerizat (deja in coada cu acelasi id?)"
            )
        return job.job_id

    def status(self, task_id: str) -> JobResult | None:
        return asyncio.run(self._status_async(task_id))

    async def _status_async(self, task_id: str) -> JobResult | None:
        pool = await self._get_pool()
        job = Job(task_id, pool)
        arq_status = await job.status()

        if arq_status != JobStatus.complete:
            return _map_status(task_id, arq_status)

        info = await job.result_info()
        return _map_result(task_id, info)
