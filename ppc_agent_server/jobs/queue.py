"""Abstractia de coada de joburi: dispecerizeaza o functie, urmareste starea prin ``task_id``.

``InlineJobQueue`` executa sincron, in acelasi proces — implicita, fara Redis,
ce folosesc Faza E si toate testele (zero retea, ca tot restul proiectului).
``ArqJobQueue`` (Faza F) trimite catre un worker real prin Redis, cu exact
acelasi contract (:class:`JobQueue`), comutata automat dupa ``REDIS_URL``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from ppc_agent_server.settings import get_server_settings

JobStatusLabel = Literal["queued", "running", "success", "failed"]


class JobResult(BaseModel):
    """Starea si rezultatul unui job, adresabil prin ``task_id``."""

    task_id: str
    status: JobStatusLabel
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class JobQueue(Protocol):
    """Contractul comun intre ``InlineJobQueue`` (Faza E) si ``ArqJobQueue`` (Faza F).

    ``enqueue`` ia direct functia (nu si un nume separat de dispecerizat): un
    ``job_name`` hand-scris, separat de ``func``, ar putea diverge de numele
    inregistrat efectiv in ``WorkerSettings.functions`` al worker-ului ARQ —
    implementarile care au nevoie de un nume (``ArqJobQueue``) il deriva din
    ``func.__name__``, garantand ca cele doua nu se pot dezalinia niciodata.
    """

    def enqueue(self, func: Callable[..., dict[str, Any]], /, **kwargs: Any) -> str:
        """Dispecerizeaza ``func(**kwargs)``; returneaza un ``task_id`` pollabil.

        ``kwargs`` trebuie sa fie serializabile (fara sesiuni DB, fara obiecte
        vii) — ``ArqJobQueue`` le trimite printr-un proces worker separat.
        """
        ...

    def status(self, task_id: str) -> JobResult | None:
        """Starea unui job dupa ``task_id``, sau ``None`` daca nu exista."""
        ...


class InlineJobQueue:
    """Executie sincrona, in proces. Job-ul se termina inainte ca ``enqueue`` sa
    returneze — starea e mereu ``success``/``failed`` la intoarcere, niciodata
    ``queued``/``running`` in practica, dar contractul de polling tot functioneaza."""

    def __init__(self) -> None:
        self._results: dict[str, JobResult] = {}

    def enqueue(self, func: Callable[..., dict[str, Any]], /, **kwargs: Any) -> str:
        task_id = str(uuid.uuid4())
        created_at = datetime.now(tz=UTC)
        try:
            result = func(**kwargs)
        except Exception as exc:
            self._results[task_id] = JobResult(
                task_id=task_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                created_at=created_at,
                finished_at=datetime.now(tz=UTC),
            )
            return task_id

        self._results[task_id] = JobResult(
            task_id=task_id,
            status="success",
            result=result,
            created_at=created_at,
            finished_at=datetime.now(tz=UTC),
        )
        return task_id

    def status(self, task_id: str) -> JobResult | None:
        return self._results.get(task_id)


_queue: JobQueue | None = None


def _default_queue(redis_url: str | None = None) -> JobQueue:
    """``InlineJobQueue`` daca ``redis_url`` e necompletat, altfel ``ArqJobQueue``.

    ``redis_url`` explicit (nu doar citit din ``get_server_settings()`` direct)
    ca sa fie testabila fara sa lupte cu cache-ul ``@lru_cache`` al setarilor —
    acelasi motiv pentru care ``create_db_engine`` din ``db.py`` accepta un
    ``settings`` optional. Importul ``arq_queue`` (si, prin el, ``arq``) e facut
    aici, nu la nivel de modul — importul lui ``queue`` (si tot ce depinde de
    el: router-e, tasks) nu trebuie sa ceara ``arq`` instalat cand nimeni nu
    foloseste coada reala.
    """
    resolved = redis_url if redis_url is not None else get_server_settings().redis_url
    if not resolved:
        return InlineJobQueue()

    from ppc_agent_server.jobs.arq_queue import ArqJobQueue

    return ArqJobQueue(resolved)


def get_job_queue() -> JobQueue:
    """Coada activa a procesului (creata lenes, o singura data — vezi ``_default_queue``)."""
    global _queue
    if _queue is None:
        _queue = _default_queue()
    return _queue


def set_job_queue(queue: JobQueue) -> None:
    """Inlocuieste coada activa — folosit de teste (o coada noua, izolata, per test)."""
    global _queue
    _queue = queue
