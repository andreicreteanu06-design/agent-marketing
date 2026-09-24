"""Registrul auditurilor pornite, tinut in memoria procesului.

``every-app/open-seo`` persista auditurile in D1/Postgres, fiindca acolo un
audit e un Workflow durabil care supravietuieste repornirilor. ``seo_geo_agent``
NU are baza de date proprie si e deliberat asa (vezi ``seo_geo_agent/__init__.py``),
deci registrul de aici accepta explicit compromisul: un audit traieste cat
traieste procesul, iar la repornirea serverului rapoartele nepreluate se pierd.

Consecinta practica, de stiut la deploy: agentul trebuie rulat cu UN SINGUR
worker uvicorn. Cu mai multi, cererea de stare poate ajunge in alt proces decat
cel care ruleaza auditul, iar clientul primeste 404 pe un audit care exista.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from seo_geo_agent.audit.service import AuditProgress, AuditResult

AuditStatus = Literal["running", "completed", "failed"]

#: Cat timp ramane un raport disponibil dupa ce s-a terminat.
RESULT_TTL = timedelta(minutes=30)
#: Audituri simultane per client. Unul singur: un audit e zeci de cereri HTTP
#: catre site-ul clientului, nu ceva ce vrei sa poata porni de 20 de ori.
MAX_RUNNING_PER_CLIENT = 1


class TooManyAuditsError(Exception):
    """Clientul are deja un audit in derulare."""


@dataclass(slots=True)
class AuditRecord:
    """Un audit: starea lui, progresul si (la final) raportul sau eroarea."""

    audit_id: str
    client_id: int
    domain: str
    status: AuditStatus = "running"
    progress: AuditProgress = field(default_factory=AuditProgress)
    result: AuditResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None


class AuditStore:
    """Dictionar cu expirare peste :class:`AuditRecord`.

    Nu are nevoie de lock: FastAPI ruleaza totul pe aceeasi bucla de evenimente,
    iar metodele de aici nu asteapta niciodata (``await``), deci nu pot fi
    intrerupte la mijloc.
    """

    def __init__(self) -> None:
        self._records: dict[str, AuditRecord] = {}

    def _evict_expired(self) -> None:
        """Sterge rapoartele expirate, dar nu si ultimul audit terminat al unui client.

        Acela ramane pana la repornirea procesului: e raportul aratat pe pagina
        de ansamblu a contului, care altfel ar disparea la 30 de minute dupa
        fiecare audit. Memoria ramane marginita - cel mult unul per client.
        """
        cutoff = datetime.now(tz=UTC) - RESULT_TTL
        keep: set[str] = set()
        for client_id in {record.client_id for record in self._records.values()}:
            latest = self._latest_completed(client_id)
            if latest is not None:
                keep.add(latest.audit_id)
        expired = [
            audit_id
            for audit_id, record in self._records.items()
            if record.finished_at is not None
            and record.finished_at < cutoff
            and audit_id not in keep
        ]
        for audit_id in expired:
            del self._records[audit_id]

    def _latest_completed(self, client_id: int) -> AuditRecord | None:
        completed = [
            record
            for record in self._records.values()
            if record.client_id == client_id and record.status == "completed"
        ]
        return max(
            completed, key=lambda record: record.finished_at or record.created_at, default=None
        )

    def latest_completed(self, client_id: int) -> AuditRecord | None:
        """Cel mai recent audit terminat cu succes al lui ``client_id``, daca exista."""
        self._evict_expired()
        return self._latest_completed(client_id)

    def create(self, client_id: int, domain: str) -> AuditRecord:
        """Inregistreaza un audit nou pentru ``client_id``.

        Raises:
            TooManyAuditsError: clientul are deja un audit in derulare.
        """
        self._evict_expired()
        running = sum(
            1
            for record in self._records.values()
            if record.client_id == client_id and record.status == "running"
        )
        if running >= MAX_RUNNING_PER_CLIENT:
            raise TooManyAuditsError
        record = AuditRecord(audit_id=uuid.uuid4().hex, client_id=client_id, domain=domain)
        self._records[record.audit_id] = record
        return record

    def get(self, client_id: int, audit_id: str) -> AuditRecord | None:
        """Auditul ``audit_id``, doar daca apartine lui ``client_id``.

        Verificarea proprietarului e aici, nu in router: un id ghicit nu trebuie
        sa dea niciodata raportul altui client.
        """
        self._evict_expired()
        record = self._records.get(audit_id)
        if record is None or record.client_id != client_id:
            return None
        return record

    def mark_completed(self, record: AuditRecord, result: AuditResult) -> None:
        record.status = "completed"
        record.result = result
        record.progress = AuditProgress(
            crawled=len(result.pages), queued=0, max_pages=record.progress.max_pages
        )
        record.finished_at = datetime.now(tz=UTC)

    def mark_failed(self, record: AuditRecord, error: str) -> None:
        record.status = "failed"
        record.error = error
        record.finished_at = datetime.now(tz=UTC)


#: Instanta unica folosita de router (vezi ``seo_geo_agent/router.py``).
audit_store = AuditStore()
