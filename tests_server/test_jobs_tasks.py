"""Teste pentru job-urile server-side: _app_config_for, propose, fatigue-check,
sincronizare metrici, mentenanta zilnica (toate DB-backed, fara HTTP)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlmodel import Session, select

import ppc_agent_server.jobs.tasks as tasks_module
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.mock.meta import MockMetaMarketingProvider
from ppc_agent_server.jobs.tasks import (
    ClientNotFoundError,
    _app_config_for,
    run_daily_maintenance_job,
    run_fatigue_check_job,
    run_metrics_sync_job,
    run_propose_job,
)
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdPerformanceRecord,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.security import encrypt_secret
from ppc_agent_server.services.queen_signals import DbFinancialSignals

#: Pasii mentenantei de noapte per client, in ordine.
STEPS = {"sync", "propose", "fatigue_check", "speed_check", "site_audit", "tracking_contract"}

def test_default_lead_value_feeds_budget_target_cpa() -> None:
    """default_lead_value alimenteaza target_cpa - activeaza sfatul de capacitate
    per buget (decision.budget_strategy) automat, fara camp separat pe client."""
    account = ClientAccount(
        tenant_id=1,
        name="Client Test",
        max_daily_spend=Decimal("20.00"),
        default_lead_value=Decimal("150.00"),
    )
    config = _app_config_for(account)
    assert config.budget.max_daily_spend == Decimal("20.00")
    assert config.budget.target_cpa == Decimal("150.00")


def test_app_config_for_falls_back_to_global_settings_when_no_secrets_connected() -> None:
    """Comportament neschimbat: client fara conturi conectate (*_enc goale,
    implicit) foloseste tot Settings() global - nu are nevoie de SECRETS_KEY
    configurat (decrypt_secret() nu se apeleaza deloc)."""
    account = ClientAccount(tenant_id=1, name="Client Fara Conturi")
    config = _app_config_for(account)
    assert config.settings.google_ads_refresh_token == ""
    assert config.settings.meta_access_token == ""
    assert config.settings.tiktok_access_token == ""


def test_app_config_for_uses_decrypted_per_client_secrets(agency_settings: Tenant) -> None:
    """Cand clientul si-a conectat contul (camp *_enc populat), _app_config_for
    foloseste secretul lui decriptat, nu Settings() global."""
    account = ClientAccount(
        tenant_id=1,
        name="Client Cu Cont Conectat",
        google_ads_refresh_token_enc=encrypt_secret("1//refresh-real-al-clientului"),
    )
    config = _app_config_for(account)
    assert config.settings.google_ads_refresh_token == "1//refresh-real-al-clientului"
    # Campurile neconectate raman goale, nu crapa.
    assert config.settings.meta_access_token == ""


def _client_account(session: Session, *, max_daily_spend: str = "50.00") -> ClientAccount:
    tenant = Tenant(name="Agentie Test", api_key_hash=f"hash-{uuid.uuid4()}")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    account = ClientAccount(
        tenant_id=tenant.id,  # type: ignore[arg-type]
        name="Client Test",
        max_daily_spend=Decimal(max_daily_spend),
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_run_propose_job_persists_pending_proposals(session: Session) -> None:
    account = _client_account(session)
    result = run_propose_job(client_account_id=account.id)
    assert result["created"] > 0

    rows = session.exec(
        select(ProposedChange).where(ProposedChange.client_account_id == account.id)
    ).all()
    assert len(rows) == result["created"]
    assert all(row.status == ChangeStatus.PENDING for row in rows)


def test_run_propose_job_unknown_client_raises(session: Session) -> None:
    """``session`` nu e folosit direct - cerut doar ca sa activeze fixture-ul ``engine``
    (DB in-memory izolat, tabele create) pe care ``get_engine()`` il rezolva mai jos."""
    with pytest.raises(ClientNotFoundError):
        run_propose_job(client_account_id=999_999)


def test_run_fatigue_check_job_proposes_pause_for_dying_ad(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_dying",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=100),
        spend=Decimal("25.00"),
        target_cpa=Decimal("10.00"),
        conversions=0,
        impressions=1600,
    )
    session.add(record)
    session.commit()

    result = run_fatigue_check_job(client_account_id=account.id)
    assert result["evaluated"] == 1
    assert result["created"] == 1

    row = session.exec(
        select(ProposedChange).where(ProposedChange.client_account_id == account.id)
    ).one()
    assert row.op == ChangeOp.PAUSE
    assert "PAUSE_HARD" in row.rationale


def test_run_fatigue_check_job_no_proposals_for_young_ad(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_new",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC) - timedelta(hours=1),  # sub tamponul Gate A
        target_cpa=Decimal("10.00"),
    )
    session.add(record)
    session.commit()

    result = run_fatigue_check_job(client_account_id=account.id)
    assert result["evaluated"] == 1
    assert result["created"] == 0


def test_run_metrics_sync_job_updates_spend_and_clicks_for_known_arm(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="c_brand",  # arm_id real din providers/mock/ads.py
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC),
        target_cpa=Decimal("10.00"),
        spend=Decimal("0"),
        clicks=0,
        conversions=7,
        revenue=Decimal("777.00"),
    )
    session.add(record)
    session.commit()

    result = run_metrics_sync_job(client_account_id=account.id)
    assert result["checked"] == 1
    assert result["updated"] == 1

    session.refresh(record)
    assert record.spend > 0
    assert record.clicks > 0
    # conversions/revenue raman neatinse - proprietatea pipeline-ului de urmarire a conversiilor.
    assert record.conversions == 7
    assert record.revenue == Decimal("777.00")


def test_run_metrics_sync_job_updates_meta_arm(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="as_brand",  # arm_id real din providers/mock/meta.py
        platform=AdFatiguePlatform.META,
        launch_time=datetime.now(tz=UTC),
        target_cpa=Decimal("10.00"),
        spend=Decimal("0"),
        clicks=0,
        conversions=3,
        revenue=Decimal("333.00"),
    )
    session.add(record)
    session.commit()

    result = run_metrics_sync_job(client_account_id=account.id)
    assert result["updated"] == 1

    session.refresh(record)
    assert record.spend > 0
    assert record.clicks > 0
    assert record.conversions == 3  # neatins, ca la Google/TikTok


def test_run_metrics_sync_job_ignores_unknown_ad_id(session: Session) -> None:
    account = _client_account(session)
    record = AdPerformanceRecord(
        client_account_id=account.id,
        ad_id="nu_exista_in_provider",
        platform=AdFatiguePlatform.GOOGLE,
        launch_time=datetime.now(tz=UTC),
        target_cpa=Decimal("10.00"),
    )
    session.add(record)
    session.commit()

    result = run_metrics_sync_job(client_account_id=account.id)
    assert result["checked"] == 1
    assert result["updated"] == 0
    session.refresh(record)
    assert record.spend == Decimal("0")


def test_run_daily_maintenance_job_processes_all_clients(session: Session) -> None:
    first = _client_account(session)
    second = _client_account(session)

    result = run_daily_maintenance_job()
    assert result["clients_processed"] >= 2
    assert str(first.id) in result["results"]
    assert str(second.id) in result["results"]
    for client_result in result["results"].values():
        assert set(client_result) == STEPS


def test_run_daily_maintenance_job_isolates_per_client_errors(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eroarea unui pas, pentru un client, nu opreste rularea celorlalti pasi/clienti."""
    account = _client_account(session)

    def _boom(*, client_account_id: int) -> dict[str, Any]:
        raise RuntimeError("simulat pentru test")

    monkeypatch.setattr(tasks_module, "run_propose_job", _boom)

    result = run_daily_maintenance_job()
    client_result = result["results"][str(account.id)]
    assert "error" in client_result["propose"]
    assert "RuntimeError" in client_result["propose"]["error"]
    assert "error" not in client_result["sync"]  # pasul urmator tot a rulat normal


# --- fan-out-ul de noapte (cron ARQ) -------------------------------------------


class _FakeArqRedis:
    """``ctx["redis"]`` al unui worker ARQ, fara Redis: tine minte ce s-a programat."""

    def __init__(self, already_queued: set[str] | None = None) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []
        self._queued = already_queued or set()

    async def enqueue_job(self, name: str, **kwargs: Any) -> object | None:
        job_id = kwargs.get("_job_id")
        if job_id in self._queued:
            return None  # ARQ: un job cu acelasi id exista deja
        self._queued.add(str(job_id))
        self.jobs.append((name, kwargs))
        return object()


def test_cronul_de_noapte_programeaza_cate_un_job_per_client(session: Session) -> None:
    import asyncio

    from ppc_agent_server.jobs.worker import _daily_maintenance_task

    first = _client_account(session)
    second = _client_account(session)
    redis = _FakeArqRedis()

    result = asyncio.run(_daily_maintenance_task({"redis": redis}))

    assert result == {"clients": 2, "enqueued": 2}
    assert {kwargs["client_account_id"] for _, kwargs in redis.jobs} == {first.id, second.id}
    assert {name for name, _ in redis.jobs} == {"run_client_maintenance_job"}
    day = datetime.now(tz=UTC).date().isoformat()
    assert {kwargs["_job_id"] for _, kwargs in redis.jobs} == {
        f"maintenance:{day}:{first.id}",
        f"maintenance:{day}:{second.id}",
    }


def test_cronul_pornit_de_doua_ori_nu_dubleaza_joburile(session: Session) -> None:
    import asyncio

    from ppc_agent_server.jobs.worker import _daily_maintenance_task

    _client_account(session)
    redis = _FakeArqRedis()
    asyncio.run(_daily_maintenance_task({"redis": redis}))
    again = asyncio.run(_daily_maintenance_task({"redis": redis}))

    assert again["enqueued"] == 0
    assert len(redis.jobs) == 1


def test_jobul_unui_client_izoleaza_pasii(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _client_account(session)

    def _boom(*, client_account_id: int) -> dict[str, Any]:
        raise RuntimeError("platforma nu raspunde")

    monkeypatch.setattr(tasks_module, "run_metrics_sync_job", _boom)

    result = tasks_module.run_client_maintenance_job(client_account_id=account.id or 0)

    assert set(result) == STEPS
    assert "RuntimeError" in result["sync"]["error"]
    assert "error" not in result["fatigue_check"]


def test_the_cfo_judges_the_same_platform_numbers_the_budget_algorithm_moves(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fara magazin conectat nu exista conversii prin webhook: CFO-ul citea "date
    insuficiente" pentru totdeauna, in timp ce Kelly muta bani pe cifrele din Meta."""
    account = _client_account(session)
    account.meta_ad_account_id = "act_1"
    session.add(account)
    session.commit()
    account_id = account.id or 0

    run_metrics_sync_job(client_account_id=account_id)  # mock: cifre inventate
    assert DbFinancialSignals(session).load(account_id).ads == []  # nu ajung la CFO

    # Pilot doar pe Meta: live, fara chei Google/TikTok; Meta raspunde fara retea.
    monkeypatch.setenv("PPC_PROVIDER_MODE", "live")
    monkeypatch.setenv("PPC_META_ACCESS_TOKEN", "token-de-test")
    monkeypatch.setattr(ProviderFactory, "meta", lambda self: MockMetaMarketingProvider())
    run_metrics_sync_job(client_account_id=account_id)
    run_metrics_sync_job(client_account_id=account_id)  # a doua noapte inlocuieste, nu dubleaza

    meta = MockMetaMarketingProvider().campaign_performance("act_1").to_dict(orient="records")
    ads = DbFinancialSignals(session).load(account_id).ads
    assert len(ads) == len(meta)
    seen = {ad.ad_id: ad for ad in ads}
    for row in meta:
        ad = seen[str(row["arm_id"])]
        assert (ad.platform, ad.spend, ad.conversions) == (
            "meta_ads",
            Decimal(str(row["cost"])).quantize(Decimal("0.01")),
            row["conversions"],
        )
