"""Teste CRUD round-trip pentru schema relationala: Tenant -> ClientAccount ->
(ProposedChange, AdQueueItem, CreativeArtifact)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent_server.models import (
    AdQueueItem,
    AdQueueStatus,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    CreativeArtifact,
    Platform,
    ProposedChange,
    SubscriptionStatus,
    Tenant,
)


def _tenant(session: Session, name: str = "Agentie Test") -> Tenant:
    tenant = Tenant(name=name, api_key_hash="hash-de-test")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def _client_account(session: Session, tenant: Tenant) -> ClientAccount:
    account = ClientAccount(
        tenant_id=tenant.id, name="Client Test", target_domain="https://exemplu.ro"
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_tenant_round_trip(session: Session) -> None:
    tenant = _tenant(session)
    assert tenant.id is not None
    assert tenant.subscription_status == SubscriptionStatus.TRIAL
    assert tenant.subscription_status == "trial"  # StrEnum: egal cu valoarea, nu doar identic

    fetched = session.get(Tenant, tenant.id)
    assert fetched is not None
    assert fetched.name == "Agentie Test"


def test_client_account_belongs_to_tenant(session: Session) -> None:
    tenant = _tenant(session)
    account = _client_account(session, tenant)

    fetched = session.get(ClientAccount, account.id)
    assert fetched is not None
    assert fetched.tenant_id == tenant.id
    assert fetched.max_daily_spend == Decimal("50.00")  # implicit


def test_tenant_relationship_lists_client_accounts(session: Session) -> None:
    tenant = _tenant(session)
    _client_account(session, tenant)
    _client_account(session, tenant)

    session.refresh(tenant)
    assert len(tenant.client_accounts) == 2


def test_proposed_change_round_trip_with_json_fields(session: Session) -> None:
    tenant = _tenant(session)
    account = _client_account(session, tenant)

    change = ProposedChange(
        client_account_id=account.id,
        op=ChangeOp.UPDATE,
        resource="campaign/c_brand",
        resource_type="campaign",
        after={"daily_budget": "30.00"},
        projected_daily_spend=Decimal("30.00"),
        rationale="Thompson Sampling: P(cel mai bun)=1.000",
        source_module="budget",
    )
    session.add(change)
    session.commit()
    session.refresh(change)

    fetched = session.get(ProposedChange, change.id)
    assert fetched is not None
    assert fetched.status == ChangeStatus.PENDING
    assert fetched.after == {"daily_budget": "30.00"}  # JSON round-trip
    assert fetched.op == ChangeOp.UPDATE


def test_proposed_change_hitl_status_transition(session: Session) -> None:
    tenant = _tenant(session)
    account = _client_account(session, tenant)
    change = ProposedChange(
        client_account_id=account.id,
        op=ChangeOp.PAUSE,
        resource="tiktok_ad_group/tt_topview",
        resource_type="ad_group",
        rationale="sub pragul minim, dezactivat",
        source_module="budget",
    )
    session.add(change)
    session.commit()
    session.refresh(change)
    assert change.status == ChangeStatus.PENDING

    change.status = ChangeStatus.EXECUTED
    change.decided_at = datetime.now(tz=UTC)
    change.decided_by = "andrei@agentie.ro"
    session.add(change)
    session.commit()
    session.refresh(change)
    assert change.status == ChangeStatus.EXECUTED
    assert change.decided_by == "andrei@agentie.ro"


def test_ad_queue_item_stores_heterogeneous_ad_copy(session: Session) -> None:
    """ad_copy e JSON tocmai pentru ca AdCopy (Google) si TikTokAdCopy difera in forma."""
    tenant = _tenant(session)
    account = _client_account(session, tenant)

    google_item = AdQueueItem(
        client_account_id=account.id,
        platform=Platform.GOOGLE,
        target_keyword="program facturare",
        emotion_trigger="fomo",
        product_usp="Factureaza in 30 de secunde",
        ad_copy={
            "headline_1": "Program facturare",
            "headline_2": "Fara stres",
            "description": "...",
        },
    )
    tiktok_item = AdQueueItem(
        client_account_id=account.id,
        platform=Platform.TIKTOK,
        target_keyword="cutie de viteze",
        emotion_trigger="frica",
        product_usp="Diagnoza rapida",
        ad_copy={
            "visual_hook_concept": "zoom",
            "audio_hook": "Nu mai face asta",
            "body_script": "...",
            "text_overlay": ["Dovedit", "Suna acum"],
            "call_to_action": "Suna acum",
            "creative_angle": "mistake_opener",
        },
    )
    session.add(google_item)
    session.add(tiktok_item)
    session.commit()
    session.refresh(google_item)
    session.refresh(tiktok_item)

    assert google_item.status == AdQueueStatus.PENDING_REVIEW
    assert isinstance(tiktok_item.ad_copy["text_overlay"], list)  # JSON pastreaza tipul


def test_creative_artifact_round_trip(session: Session) -> None:
    tenant = _tenant(session)
    account = _client_account(session, tenant)

    artifact = CreativeArtifact(
        client_account_id=account.id,
        platform=Platform.TIKTOK,
        keyword="cutie de viteze",
        wav_path="creative_output/x.wav",
        mp4_path="creative_output/x.mp4",
        duration_seconds=25.8,
        manifest={"aspect_ratio": "9:16", "video_engine": "mock-flick"},
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)

    fetched = session.get(CreativeArtifact, artifact.id)
    assert fetched is not None
    assert fetched.manifest["aspect_ratio"] == "9:16"


def test_query_pending_changes_for_client(session: Session) -> None:
    tenant = _tenant(session)
    account = _client_account(session, tenant)
    for i in range(3):
        session.add(
            ProposedChange(
                client_account_id=account.id,
                op=ChangeOp.UPDATE,
                resource=f"campaign/c_{i}",
                resource_type="campaign",
                rationale="test",
                source_module="budget",
            )
        )
    session.commit()

    pending = session.exec(
        select(ProposedChange).where(
            ProposedChange.client_account_id == account.id,
            ProposedChange.status == ChangeStatus.PENDING,
        )
    ).all()
    assert len(pending) == 3
