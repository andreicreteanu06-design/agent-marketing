"""Limitarea frecventei: forta bruta pe login si costul modelelor pe chatul Reginei.

Limitele sunt in memoria procesului; ``conftest._fresh_rate_limits`` le goleste
inainte de fiecare test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ppc_agent_server.models import Tenant
from ppc_agent_server.rate_limit import (
    CHAT_BURST,
    LOGIN_BY_IP,
    LOGIN_FAILURES_BY_EMAIL,
    SIGNUP_BY_IP,
    RateLimiter,
)
from tests_server.test_client_auth import _signup

_EMAIL = "client@exemplu.ro"
_PASSWORD = "parola-super-sigura"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- limitatorul ---------------------------------------------------------------------


def test_the_window_slides_instead_of_resetting_at_a_fixed_boundary() -> None:
    clock = _Clock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)

    assert limiter.hit("k") is None
    clock.now += 30
    assert limiter.hit("k") is None
    assert limiter.hit("k") == pytest.approx(30)  # primul hit iese din fereastra peste 30s
    clock.now += 31
    assert limiter.hit("k") is None  # a iesit unul, a intrat altul
    assert limiter.hit("k") is not None


def test_keys_are_independent_and_can_be_cleared() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=_Clock())

    assert limiter.hit("a") is None
    assert limiter.hit("b") is None
    assert limiter.retry_after("a") is not None
    limiter.clear("a")
    assert limiter.retry_after("a") is None


def test_a_blocked_request_is_not_counted() -> None:
    clock = _Clock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.hit("k")
    for _ in range(5):
        limiter.hit("k")  # refuzate - nu prelungesc blocarea
    clock.now += 60
    assert limiter.hit("k") is None


# --- login: forta bruta --------------------------------------------------------------


def _login(client: TestClient, password: str, email: str = _EMAIL) -> int:
    return client.post("/api/v1/login", json={"email": email, "password": password}).status_code


def test_after_five_wrong_passwords_even_the_right_one_waits(
    client: TestClient, agency_settings: Tenant
) -> None:
    _signup(client)
    for _ in range(LOGIN_FAILURES_BY_EMAIL.limit):
        assert _login(client, "gresita-de-tot") == 401

    blocked = client.post("/api/v1/login", json={"email": _EMAIL, "password": _PASSWORD})

    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.json()["detail"].startswith("Prea multe încercări de autentificare.")
    assert "minute" in blocked.json()["detail"]


def test_a_successful_login_clears_the_failures(
    client: TestClient, agency_settings: Tenant
) -> None:
    _signup(client)
    for _ in range(LOGIN_FAILURES_BY_EMAIL.limit - 1):
        _login(client, "gresita")
    assert _login(client, _PASSWORD) == 200
    for _ in range(LOGIN_FAILURES_BY_EMAIL.limit - 1):
        assert _login(client, "gresita") == 401  # numaratoarea a reinceput


def test_the_email_limit_is_case_insensitive(client: TestClient, agency_settings: Tenant) -> None:
    _signup(client)
    for index in range(LOGIN_FAILURES_BY_EMAIL.limit):
        _login(client, "gresita", email=_EMAIL.upper() if index % 2 else _EMAIL)
    assert _login(client, _PASSWORD) == 429


def test_one_ip_cannot_spray_many_accounts(client: TestClient, agency_settings: Tenant) -> None:
    for index in range(LOGIN_BY_IP.limit):
        assert _login(client, "x", email=f"cont{index}@exemplu.ro") == 401
    assert _login(client, "x", email="inca-unul@exemplu.ro") == 429


# --- signup: conturi in masa -------------------------------------------------------


def test_one_ip_cannot_create_accounts_in_bulk(client: TestClient, agency_settings: Tenant) -> None:
    for index in range(SIGNUP_BY_IP.limit):
        _signup(client, email=f"cont{index}@exemplu.ro")
    blocked = client.post(
        "/api/v1/signup",
        json={"name": "Robot", "email": "robot@exemplu.ro", "password": "parola-robot-123"},
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_signups_with_a_taken_email_count_too(client: TestClient, agency_settings: Tenant) -> None:
    """Altfel 409-ul ar spune nelimitat ce adrese au cont."""
    _signup(client)

    def attempt(email: str) -> int:
        payload = {"name": "X", "email": email, "password": "parola-12345"}
        return client.post("/api/v1/signup", json=payload).status_code

    for _ in range(SIGNUP_BY_IP.limit - 1):
        assert attempt(_EMAIL) == 409
    assert attempt("alt@exemplu.ro") == 429


# --- chatul Reginei: costul modelelor (Ollama local, Jev) ----------------------------


def _chat(client: TestClient, headers: dict[str, str]) -> int:
    return client.post(
        "/api/v1/queen/chat", headers=headers, json={"message": "Merită să cresc bugetul?"}
    ).status_code


def test_the_chat_stops_a_burst_per_client(client: TestClient, agency_settings: Tenant) -> None:
    from ppc_agent_server.routers import queen
    from tests_server.test_brand_alignment import _FakeSeoIntent

    app = client.app
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent()  # type: ignore[attr-defined]
    app.dependency_overrides[queen.get_cmo_voice] = lambda: None  # type: ignore[attr-defined]
    try:
        first = {"Authorization": f"Bearer {_signup(client)['access_token']}"}
        second = {
            "Authorization": "Bearer "
            + str(_signup(client, email="altul@exemplu.ro", name="Alt Client")["access_token"])
        }

        for _ in range(CHAT_BURST.limit):
            assert _chat(client, first) == 200
        blocked = client.post(
            "/api/v1/queen/chat", headers=first, json={"message": "Și TikTok?"}
        )
        assert blocked.status_code == 429
        assert blocked.json()["detail"].startswith("Ai trimis multe întrebări")
        assert _chat(client, second) == 200  # alt client nu plateste pentru primul
    finally:
        app.dependency_overrides.clear()  # type: ignore[attr-defined]
