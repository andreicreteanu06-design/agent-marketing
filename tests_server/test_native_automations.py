"""Native workflow contracts: no external email, AI service or customer database."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ppc_agent_server.automations import delivery, planner
from ppc_agent_server.automations.catalog import example
from ppc_agent_server.automations.planner import build_plan
from ppc_agent_server.automations.schemas import INPUTS, Configuration
from ppc_agent_server.models import Tenant
from ppc_agent_server.settings import get_server_settings

NOW = datetime(2026, 10, 5, 10, tzinfo=UTC)
CFG = Configuration(enabled=True, company_name="Demo", team_email="team@example.com")


@pytest.mark.parametrize("slug", list(INPUTS))
def test_all_nine_have_native_plans(slug):
    plan = build_plan(slug, example(slug), CFG, allow_ai=False)
    assert plan.steps
    assert plan.summary
    assert plan.stage


def test_stock_above_threshold_has_no_messages():
    data = example("stoc") | {"stock": 8}
    assert build_plan("stoc", data, CFG).skipped
    assert not build_plan("stoc", data, CFG).messages


def test_paid_invoices_and_future_delivery_do_not_send():
    assert build_plan("facturi", example("facturi") | {"paid": True}, CFG).skipped
    assert build_plan(
        "reviewuri", example("reviewuri") | {"delivered_at": "2099-01-01"}, CFG
    ).skipped


def test_invoice_escalation_only_contacts_owner():
    plan = build_plan("facturi", example("facturi") | {"due_date": "2026-08-01"}, CFG, now=NOW)
    assert plan.stage == "escalation"
    assert [m.recipient for m in plan.messages] == [CFG.team_email]


def test_hr_never_scores_or_contacts_candidate_automatically():
    plan = build_plan("cv", example("cv"), CFG, allow_ai=False)
    assert all(m.requires_review for m in plan.messages)
    assert all(m.recipient == CFG.team_email for m in plan.messages)
    assert "score" not in plan.output and "rank" not in plan.output


def test_marketing_has_four_drafts_and_requires_approval():
    plan = build_plan("continut", example("continut"), CFG, allow_ai=False)
    assert set(plan.output["channels"]) == {"LinkedIn", "Facebook", "Instagram", "Newsletter"}
    assert all(m.requires_review for m in plan.messages)
    assert plan.output["generation"] == "template"


def test_onboarding_stages_and_completed_form():
    raw = example("onboarding") | {"started_at": "2026-10-01", "form_completed": False}
    assert build_plan("onboarding", raw, CFG, now=NOW).stage == "reminder"
    assert build_plan("onboarding", raw | {"form_completed": True}, CFG, now=NOW).skipped
    assert build_plan("onboarding", raw, CFG, now=NOW + timedelta(days=5)).stage == "checkin"


@pytest.mark.parametrize(
    "patch", [{"email": "x@example.com\nBcc:bad@example.com"}, {"email": "invalid"}]
)
def test_email_validation_rejects_header_injection(patch):
    with pytest.raises(ValueError):
        build_plan("comenzi", example("comenzi") | patch, CFG)


def test_review_link_rejects_javascript():
    with pytest.raises(ValueError):
        build_plan("reviewuri", example("reviewuri") | {"review_url": "javascript:alert(1)"}, CFG)


BASE = "/api/v1/me/automations"


@pytest.fixture(autouse=True)
def native_offline(monkeypatch):
    monkeypatch.setenv("AUTOMATION_EMAIL_ENABLED", "false")
    get_server_settings.cache_clear()
    monkeypatch.setattr(planner, "generate_copy", lambda *args: None)

    def forbidden(message):
        raise AssertionError("Real SMTP forbidden in native workflow tests")

    monkeypatch.setattr(delivery, "send_smtp", forbidden)
    yield
    get_server_settings.cache_clear()


def signup(client, email):
    response = client.post(
        "/api/v1/signup",
        json={"name": "Native Demo", "email": email, "password": "sigura-test-123"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def owner(client: TestClient, agency_settings: Tenant):
    return signup(client, "native@example.com")


def enable(client, owner, slug="comenzi", mode="review"):
    response = client.put(
        f"{BASE}/{slug}/settings",
        headers=owner,
        json={**CFG.model_dump(mode="json"), "delivery_mode": mode},
    )
    assert response.status_code == 200, response.text
    return response.json()


def event(client, owner, slug="comenzi", data=None, event_id="test-event"):
    response = client.post(
        f"{BASE}/{slug}/events",
        headers=owner,
        json={"event_id": event_id, "data": data or example(slug)},
    )
    assert response.status_code == 202, response.text
    return response.json()


def state(client, owner):
    response = client.get(BASE, headers=owner)
    assert response.status_code == 200, response.text
    return response.json()


def test_routes_require_customer_login(client):
    assert client.get(BASE).status_code == 401


def test_preview_is_read_only_and_nine_catalog_entries(client, owner):
    before = state(client, owner)
    assert len(before["workflows"]) == 9
    assert not before["email_ready"]
    result = client.post(
        f"{BASE}/comenzi/preview",
        headers=owner,
        json={"event_id": "preview", "data": example("comenzi")},
    )
    assert result.status_code == 200, result.text
    assert len(result.json()["messages"]) == 2
    after = state(client, owner)
    assert after["runs"] == after["records"] == after["messages"] == []


def test_disabled_workflow_rejects_events(client, owner):
    response = client.post(
        f"{BASE}/comenzi/events",
        headers=owner,
        json={"event_id": "event", "data": example("comenzi")},
    )
    assert response.status_code == 409


def test_order_deduplication_and_approval_by_default(client, owner):
    enable(client, owner)
    first = event(client, owner)
    second = event(client, owner, event_id="different-delivery-of-same-order")
    assert second["duplicate"] and second["run_id"] == first["run_id"]
    data = state(client, owner)
    assert len(data["runs"]) == 1 and data["runs"][0]["status"] == "prepared"
    assert len(data["messages"]) == 2
    assert all(m["status"] == "pending" for m in data["messages"])
    conflict = client.post(
        f"{BASE}/comenzi/events",
        headers=owner,
        json={"event_id": "other", "data": example("comenzi") | {"total": "999.00"}},
    )
    assert conflict.status_code == 409


def test_other_customer_cannot_read_or_approve(client, owner, agency_settings):
    enable(client, owner)
    event(client, owner)
    private = state(client, owner)
    other = signup(client, "other-native@example.com")
    assert state(client, other)["runs"] == []
    msg = private["messages"][0]["id"]
    assert client.post(f"{BASE}/messages/{msg}/approve", headers=other).status_code == 404
    record = private["records"][0]["id"]
    assert (
        client.put(f"{BASE}/records/{record}", headers=other, json=example("comenzi")).status_code
        == 404
    )


def test_webhook_scoped_rotatable_revocable_and_not_login_key(client, owner):
    enable(client, owner, "stoc")
    response = client.post(f"{BASE}/stoc/webhook-key", headers=owner)
    assert response.status_code == 200
    created = response.json()
    path = created["webhook_url"].split("/api/v1/")[1]
    headers = {"Authorization": "Bearer " + created["key"]}
    body = {"event_id": "stock1", "data": example("stoc")}
    assert client.post("/api/v1/" + path, headers=headers, json=body).status_code == 202
    assert client.get(BASE, headers=headers).status_code == 401
    assert "auto_" not in str(state(client, owner))
    client.delete(f"{BASE}/stoc/webhook-key", headers=owner)
    assert client.post("/api/v1/" + path, headers=headers, json=body).status_code == 401


def test_smtp_not_configured_is_blocked_not_sent(client, owner):
    enable(client, owner)
    event(client, owner)
    msg = state(client, owner)["messages"][0]["id"]
    response = client.post(f"{BASE}/messages/{msg}/approve", headers=owner)
    assert response.status_code == 200 and response.json()["status"] == "blocked"


def test_delivery_is_claimed_once_and_approval_is_required(client, owner, monkeypatch):
    enable(client, owner)
    event(client, owner)
    msg = state(client, owner)["messages"][0]["id"]
    calls = []
    monkeypatch.setattr(delivery, "email_ready", lambda: True)
    monkeypatch.setattr(delivery, "send_smtp", lambda m: calls.append(m.id))
    assert delivery.deliver_message(message_id=msg)["status"] == "not_ready"
    assert client.post(f"{BASE}/messages/{msg}/approve", headers=owner).json()["status"] == "sent"
    delivery.deliver_message(message_id=msg)
    assert calls == [msg]
    assert client.post(f"{BASE}/messages/{msg}/approve", headers=owner).status_code == 409


def test_ambiguous_smtp_failure_is_never_automatically_retried(client, owner, monkeypatch):
    enable(client, owner)
    event(client, owner)
    msg = state(client, owner)["messages"][0]["id"]
    calls = []

    def uncertain(m):
        calls.append(m.id)
        raise TimeoutError("connection lost after DATA")

    monkeypatch.setattr(delivery, "email_ready", lambda: True)
    monkeypatch.setattr(delivery, "send_smtp", uncertain)
    assert (
        client.post(f"{BASE}/messages/{msg}/approve", headers=owner).json()["status"] == "uncertain"
    )
    delivery.deliver_message(message_id=msg)
    assert client.post(f"{BASE}/messages/{msg}/approve", headers=owner).status_code == 409
    assert calls == [msg]


def test_paid_update_cancels_waiting_invoice_and_scheduler_deduplicates(client, owner):
    enable(client, owner, "facturi")
    payload = example("facturi")
    event(client, owner, "facturi", payload)
    record = state(client, owner)["records"][0]["id"]
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 0
    assert (
        client.put(
            f"{BASE}/records/{record}", headers=owner, json=payload | {"paid": True}
        ).status_code
        == 200
    )
    data = state(client, owner)
    assert all(m["status"] == "cancelled" for m in data["messages"])
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 0


def test_auto_mode_cannot_bypass_hr_review(client, owner):
    enable(client, owner, "cv", "automatic")
    event(client, owner, "cv")
    messages = state(client, owner)["messages"]
    assert all(m["status"] == "pending" and m["requires_review"] for m in messages)
    assert all(m["recipient"] == CFG.team_email for m in messages)


def test_invalid_payload_has_no_records(client, owner):
    enable(client, owner, "stoc")
    bad = client.post(
        f"{BASE}/stoc/events",
        headers=owner,
        json={"event_id": "bad", "data": example("stoc") | {"stock": -1}},
    )
    assert bad.status_code == 422
    assert not state(client, owner)["records"]


def test_maximum_marketing_and_stock_inputs_still_make_bounded_messages():
    content = example("continut") | {
        "idea": "a" * 8000,
        "audience": "b" * 500,
        "objective": "c" * 500,
    }
    plan = build_plan("continut", content, CFG, allow_ai=False)
    assert all(len(m.body) <= 24000 for m in plan.messages)
    plan = build_plan("stoc", example("stoc") | {"product_name": "a" * 250}, CFG)
    assert all(len(m.subject) <= 250 for m in plan.messages)


def test_scheduler_creates_due_review_once_after_delivery_update(client, owner):
    enable(client, owner, "reviewuri")
    future = example("reviewuri") | {"delivered_at": "2099-01-01"}
    event(client, owner, "reviewuri", future)
    current = state(client, owner)
    assert current["runs"][0]["status"] == "skipped"
    record_id = current["records"][0]["id"]
    due = future | {"delivered_at": "2026-01-01"}
    assert client.put(f"{BASE}/records/{record_id}", headers=owner, json=due).status_code == 200
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 1
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 0
    assert len(state(client, owner)["messages"]) == 1


def test_message_workflow_is_available_without_its_run_in_recent_page(client, owner):
    enable(client, owner)
    event(client, owner)
    assert all(m["workflow"] == "comenzi" for m in state(client, owner)["messages"])


def test_delayed_invoice_job_cannot_execute_a_later_stage_twice(client, owner, monkeypatch):
    from ppc_agent_server.automations import service
    from ppc_agent_server.routers import automations as routes

    enable(client, owner, "facturi")
    original = service.build_plan
    day = [NOW]
    monkeypatch.setattr(service, "build_plan", lambda *a, **kw: original(*a, **kw, now=day[0]))
    monkeypatch.setattr(routes, "enqueue_run", lambda run_id: None)
    payload = example("facturi") | {"due_date": "2026-10-04"}
    queued = event(client, owner, "facturi", payload)
    day[0] = NOW + timedelta(days=7)
    assert service.run_automation_job(run_id=queued["run_id"])["status"] == "skipped"
    assert not state(client, owner)["messages"]
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 1
    latest = state(client, owner)["runs"][0]
    service.run_automation_job(run_id=latest["id"])
    assert len(state(client, owner)["messages"]) == 1
    assert client.post(BASE + "/check-due", headers=owner).json()["scheduled"] == 0


def test_old_invoice_draft_is_not_sent_after_its_stage_has_expired(client, owner, monkeypatch):
    from ppc_agent_server.automations import service

    enable(client, owner, "facturi")
    original = service.build_plan
    monkeypatch.setattr(service, "build_plan", lambda *a, **kw: original(*a, **kw, now=NOW))
    event(client, owner, "facturi", example("facturi") | {"due_date": "2026-10-04"})
    msg = state(client, owner)["messages"][0]["id"]
    monkeypatch.setattr(delivery, "email_ready", lambda: True)
    monkeypatch.setattr(
        planner, "build_plan", lambda *a, **kw: original(*a, **kw, now=NOW + timedelta(days=7))
    )
    calls = []
    monkeypatch.setattr(delivery, "send_smtp", lambda m: calls.append(m.id))
    result = client.post(f"{BASE}/messages/{msg}/approve", headers=owner)
    assert result.json()["status"] == "cancelled"
    assert calls == []
