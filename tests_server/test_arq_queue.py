"""Teste pentru coada ARQ+Redis (Faza F) — fara Redis real (nu exista in acest mediu).

Onestitate in testare: ``ArqJobQueue`` ocupa acelasi statut epistemic ca
``LiveGoogleAdsProvider`` etc. deja in proiect — structural completa si
testabila unitar la limita (constructie, selectie, maparea starilor ARQ), dar
verificata impotriva unui Redis real doar manual/opt-in, prin design (la fel
cum testele ``LiveLLMClient`` nu ating niciodata un Ollama real, doar
``httpx.MockTransport``). Nicio metoda testata aici face I/O de retea.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arq.jobs import JobResult as ArqJobResult
from arq.jobs import JobStatus

from ppc_agent_server.jobs.arq_queue import ArqJobQueue, _map_result, _map_status
from ppc_agent_server.jobs.queue import InlineJobQueue, _default_queue
from ppc_agent_server.jobs.worker import (
    CLIENT_MAINTENANCE_TIMEOUT_SECONDS,
    WorkerSettings,
    run_client_maintenance_job,
    run_copy_job,
    run_creative_job,
    run_fatigue_check_job,
    run_metrics_sync_job,
    run_plan_job,
    run_propose_job,
)

_REDIS_URL = "redis://localhost:6379/0"


def test_default_queue_returns_inline_when_no_redis_url() -> None:
    assert isinstance(_default_queue(""), InlineJobQueue)


def test_default_queue_returns_arq_when_redis_url_set() -> None:
    queue = _default_queue(_REDIS_URL)
    assert isinstance(queue, ArqJobQueue)


def test_arq_job_queue_construction_is_lazy_no_network() -> None:
    """Construirea NU se conecteaza la Redis — doar prima folosire (enqueue/status)."""
    queue = ArqJobQueue(_REDIS_URL)
    assert queue._pool is None  # exact ce verificam: nimic initializat inca


def test_map_status_queued_and_deferred() -> None:
    for status in (JobStatus.queued, JobStatus.deferred):
        result = _map_status("t1", status)
        assert result is not None
        assert result.status == "queued"


def test_map_status_in_progress() -> None:
    result = _map_status("t1", JobStatus.in_progress)
    assert result is not None
    assert result.status == "running"


def test_map_status_not_found_returns_none() -> None:
    assert _map_status("t1", JobStatus.not_found) is None


def test_map_status_complete_defers_to_map_result() -> None:
    """complete nu e mapat direct - ArqJobQueue._status_async trece la _map_result."""
    assert _map_status("t1", JobStatus.complete) is None


def _arq_result(*, success: bool, result: object) -> ArqJobResult:
    now = datetime.now(tz=UTC)
    return ArqJobResult(
        function="run_plan_job",
        args=(),
        kwargs={},
        job_try=1,
        enqueue_time=now,
        score=None,
        job_id="t1",
        success=success,
        result=result,
        start_time=now,
        finish_time=now,
        queue_name="arq:queue",
    )


def test_map_result_success_carries_result_payload() -> None:
    info = _arq_result(success=True, result={"kelly": {"edge": "pozitiv"}})
    mapped = _map_result("t1", info)
    assert mapped.status == "success"
    assert mapped.result == {"kelly": {"edge": "pozitiv"}}
    assert mapped.error is None


def test_map_result_failure_carries_error_not_result() -> None:
    info = _arq_result(success=False, result="ClientNotFoundError: clientul 99 nu exista")
    mapped = _map_result("t1", info)
    assert mapped.status == "failed"
    assert mapped.result is None
    assert "ClientNotFoundError" in (mapped.error or "")


def test_map_result_none_is_transient_running() -> None:
    """complete conform statusului dar result_info() inca None - tranzitoriu, nu eroare."""
    mapped = _map_result("t1", None)
    assert mapped.status == "running"


def test_worker_settings_registers_all_functions_with_original_names() -> None:
    names = {registered.name for registered in WorkerSettings.functions}
    assert names == {
        run_plan_job.__name__,
        run_copy_job.__name__,
        run_creative_job.__name__,
        run_propose_job.__name__,
        run_fatigue_check_job.__name__,
        run_metrics_sync_job.__name__,
        run_client_maintenance_job.__name__,
    }


def test_client_maintenance_has_its_own_timeout_and_no_blind_retry() -> None:
    (registered,) = [
        f for f in WorkerSettings.functions if f.name == run_client_maintenance_job.__name__
    ]
    assert registered.timeout_s == CLIENT_MAINTENANCE_TIMEOUT_SECONDS
    assert registered.max_tries == 1


def test_worker_settings_registers_daily_maintenance_cron() -> None:
    names = {job.name for job in WorkerSettings.cron_jobs}
    assert names == {"daily_maintenance", "weekly_reports"}


def test_weekly_reports_run_monday_morning() -> None:
    """Luni dimineata: saptamana raportata tocmai s-a incheiat."""
    (job,) = [job for job in WorkerSettings.cron_jobs if job.name == "weekly_reports"]
    assert job.weekday == {0}
    assert job.hour == {6}


def test_worker_settings_redis_settings_parses_dsn_without_connecting() -> None:
    settings = WorkerSettings.redis_settings
    assert settings.host == "localhost"
    assert settings.port == 6379
