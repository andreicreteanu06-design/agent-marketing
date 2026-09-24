"""Registrul auditurilor: expirarea rapoartelor si "ultimul audit" al clientului.

Pagina de ansamblu a contului arata ultimul audit terminat. Rapoartele expira
la 30 de minute dupa final, dar cel mai recent al fiecarui client ramane pana
la repornirea procesului - altfel cardul de pe pagina de ansamblu ar disparea
la o jumatate de ora dupa fiecare audit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from seo_geo_agent.audit.scoring import PillarScore
from seo_geo_agent.audit.service import AuditResult
from seo_geo_agent.audit.store import RESULT_TTL, AuditRecord, AuditStore


def _result() -> AuditResult:
    now = datetime.now(tz=UTC)
    return AuditResult(
        start_url="https://exemplu.ro/",
        origin="https://exemplu.ro",
        brand="exemplu",
        started_at=now,
        finished_at=now,
        completed=True,
        robots_txt_found=True,
        llms_txt_found=False,
        sitemap_urls_found=0,
        scores={"seo": PillarScore(90, 10, 1, 20.0, 2.0), "geo": PillarScore(70, 5, 1, 10.0, 3.0)},
    )


def _completed(store: AuditStore, client_id: int, finished_ago: timedelta) -> AuditRecord:
    record = store.create(client_id, "exemplu.ro")
    store.mark_completed(record, _result())
    record.finished_at = datetime.now(tz=UTC) - finished_ago
    return record


def test_ultimul_audit_terminat_ramane_si_dupa_ce_celelalte_expira() -> None:
    store = AuditStore()
    older = _completed(store, 1, RESULT_TTL * 4)
    newest = _completed(store, 1, RESULT_TTL * 2)

    assert store.latest_completed(1) is newest
    assert store.get(1, newest.audit_id) is newest
    assert store.get(1, older.audit_id) is None


def test_fara_niciun_audit_terminat_nu_exista_ultimul_audit() -> None:
    store = AuditStore()
    store.create(1, "exemplu.ro")  # inca ruleaza
    failed = store.create(2, "exemplu.ro")
    store.mark_failed(failed, "site inaccesibil")

    assert store.latest_completed(1) is None
    assert store.latest_completed(2) is None


def test_ultimul_audit_e_al_fiecarui_client_nu_al_registrului() -> None:
    store = AuditStore()
    mine = _completed(store, 1, timedelta(minutes=5))
    _completed(store, 2, timedelta(minutes=1))

    assert store.latest_completed(1) is mine
    assert store.latest_completed(3) is None
