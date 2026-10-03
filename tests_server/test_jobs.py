"""Teste end-to-end pentru dispecerizarea de job-uri: POST /jobs/* -> GET /jobs/{task_id}.

``InlineJobQueue`` executa sincron (vezi fixture-ul ``_isolated_job_queue`` in
conftest), deci un job e mereu ``success``/``failed`` pana revine ``POST`` —
testele verifica exact acest round-trip complet, fara Redis.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.models import ClientAccount, Tenant


def _create_client(
    client: TestClient, auth_headers: dict[str, str], **overrides: object
) -> int:
    payload: dict[str, object] = {"name": "Client Test", "max_daily_spend": "60.00"}
    payload.update(overrides)
    response = client.post("/api/v1/clients", headers=auth_headers, json=payload)
    assert response.status_code == 201
    return int(response.json()["id"])


def test_dispatch_plan_job_full_round_trip(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)

    dispatch = client.post(
        "/api/v1/jobs/plan", headers=auth_headers, json={"client_id": client_id}
    )
    assert dispatch.status_code == 202
    task_id = dispatch.json()["task_id"]
    assert dispatch.json()["status"] == "success"  # InlineJobQueue a terminat deja

    status = client.get(f"/api/v1/jobs/{task_id}", headers=auth_headers)
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "success"
    assert body["error"] is None
    # PlanResult.model_dump(mode="json") - Kelly + Thompson + Markov
    assert "kelly" in body["result"]
    assert "budget_plan" in body["result"]
    assert "attribution" in body["result"]
    assert body["result"]["kelly"]["edge"] in ("pozitiv", "neutru", "negativ", "date_insuficiente")


def test_dispatch_propose_job_creates_pending_proposals(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)

    dispatch = client.post(
        "/api/v1/jobs/propose", headers=auth_headers, json={"client_id": client_id}
    )
    assert dispatch.status_code == 202
    assert dispatch.json()["status"] == "success"

    proposals = client.get(f"/api/v1/proposals/{client_id}", headers=auth_headers)
    assert proposals.status_code == 200
    assert len(proposals.json()) > 0
    assert all(item["status"] == "pending" for item in proposals.json())


def test_dispatch_fatigue_check_job_for_client_with_no_ads(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)

    dispatch = client.post(
        "/api/v1/jobs/fatigue-check", headers=auth_headers, json={"client_id": client_id}
    )
    assert dispatch.status_code == 202
    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    assert status.json()["result"] == {"evaluated": 0, "created": 0, "superseded": 0}


def test_dispatch_sync_metrics_job_for_client_with_no_records(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)

    dispatch = client.post(
        "/api/v1/jobs/sync-metrics", headers=auth_headers, json={"client_id": client_id}
    )
    assert dispatch.status_code == 202
    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    # mock: cifrele inventate nu ajung la CFO (rezumatul platformelor ramane gol)
    assert status.json()["result"] == {"checked": 0, "updated": 0, "platform_arms": 0}


def test_dispatch_copy_job_writes_ad_queue_item(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    client_id = _create_client(client, auth_headers)

    dispatch = client.post(
        "/api/v1/jobs/copy",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "keyword": "program facturare",
            "usp": "Factureaza in 30 de secunde",
            "trigger": "fomo",
            "platform": "google",
        },
    )
    assert dispatch.status_code == 202
    assert dispatch.json()["status"] == "success"

    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    result = status.json()["result"]
    assert "ad_queue_item_id" in result
    assert set(result["ad_copy"]) == {"headline_1", "headline_2", "description"}


def test_dispatch_copy_job_tiktok_platform(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    client_id = _create_client(client, auth_headers)
    dispatch = client.post(
        "/api/v1/jobs/copy",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "keyword": "cutie de viteze",
            "usp": "Diagnoza rapida",
            "trigger": "frica",
            "platform": "tiktok",
        },
    )
    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    ad_copy = status.json()["result"]["ad_copy"]
    assert "audio_hook" in ad_copy
    assert isinstance(ad_copy["text_overlay"], list)


def test_dispatch_creative_job_writes_artifact(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    client_id = _create_client(client, auth_headers)
    broll = tmp_path / "broll.mp4"
    broll.write_bytes(b"fake broll")

    dispatch = client.post(
        "/api/v1/jobs/creative",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "keyword": "curs excel",
            "broll_path": str(broll),
            "trigger": "aida",
            "platform": "google",
        },
    )
    assert dispatch.status_code == 202
    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    body = status.json()
    assert body["status"] == "success"
    assert Path(body["result"]["mp4_path"]).is_file()


def test_dispatch_creative_job_missing_broll_fails_gracefully(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    client_id = _create_client(client, auth_headers)
    dispatch = client.post(
        "/api/v1/jobs/creative",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "keyword": "curs excel",
            "broll_path": str(tmp_path / "nu_exista.mp4"),
            "platform": "google",
        },
    )
    status = client.get(f"/api/v1/jobs/{dispatch.json()['task_id']}", headers=auth_headers)
    body = status.json()
    assert body["status"] == "failed"
    assert "VideoAssemblyError" in body["error"]


def test_dispatch_job_for_unowned_client_returns_404(
    client: TestClient, auth_headers: dict[str, str], session: Session
) -> None:
    other_tenant = Tenant(name="Alta agentie", api_key_hash="alt-hash")
    session.add(other_tenant)
    session.commit()
    session.refresh(other_tenant)
    other_account = ClientAccount(tenant_id=other_tenant.id, name="Clientul altcuiva")
    session.add(other_account)
    session.commit()
    session.refresh(other_account)

    response = client.post(
        "/api/v1/jobs/plan", headers=auth_headers, json={"client_id": other_account.id}
    )
    assert response.status_code == 404


def test_job_status_unknown_task_id_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/jobs/nu-exista-un-asa-task", headers=auth_headers)
    assert response.status_code == 404


def test_job_endpoints_require_auth(client: TestClient) -> None:
    assert client.post("/api/v1/jobs/plan", json={"client_id": 1}).status_code == 401
    assert client.get("/api/v1/jobs/orice").status_code == 401
