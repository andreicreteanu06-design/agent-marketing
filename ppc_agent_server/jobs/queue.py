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
    """Contractul comun intre ``InlineJobQueue`` (Faza E) si ``ArqJobQueue`` (Faza F)."""

    def enqueue(
        self, job_name: str, func: Callable[..., dict[str, Any]], /, **kwargs: Any
    ) -> str:
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

    def enqueue(
        self, job_name: str, func: Callable[..., dict[str, Any]], /, **kwargs: Any
    ) -> str:
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


def get_job_queue() -> JobQueue:
    """Coada activa a procesului (creata lenes, o singura data — ``InlineJobQueue``
    implicit; Faza F comuta pe ``ArqJobQueue`` dupa ``REDIS_URL``)."""
    global _queue
    if _queue is None:
        _queue = InlineJobQueue()
    return _queue


def set_job_queue(queue: JobQueue) -> None:
    """Inlocuieste coada activa — folosit de teste (o coada noua, izolata, per test)."""
    global _queue
    _queue = queue
