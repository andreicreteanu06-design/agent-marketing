"""Monitorizarea sintetica: interceptarea GA4/Meta, contractul, dovezile si scutul SSRF.

Logica (clasificarea cererilor, verdictul, pachetul de dovezi, mediana PageSpeed)
se verifica fara browser. Testele marcate ``chromium`` pornesc un Chromium real pe
un site local (``synthetic_site.py``): raspunsurile GA4/Meta sunt date local, deci
nimic nu iese din masina. Fara Chromium instalat, ele se sar.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent_server.jobs import synthetic
from ppc_agent_server.jobs.synthetic import (
    contract_for,
    record_journey,
    run_tracking_contract_job,
)
from ppc_agent_server.jobs.tasks import median_pagespeed, run_speed_check_job
from ppc_agent_server.models import ClientAccount, SiteSpeedSample, TrackingEvidence
from ppc_agent_server.services.queen_signals import DbTechnicalSignals
from ppc_agent_server.services.tracking_contract import (
    DEFAULT_CONSENT_SELECTORS,
    CollectHit,
    JourneyRecord,
    TrackingContract,
    evaluate_journey,
    parse_collect_hit,
)
from tests_server.synthetic_site import page, serve
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_router import signed_in  # noqa: F401 - fixture

GA4 = "https://region1.google-analytics.com/g/collect"
META = "https://www.facebook.com/tr/"
CONTRACT = TrackingContract(
    url="https://autofix.ro/contact",
    cta_selector="#contact-btn",
    ga4_events=("page_view", "generate_lead"),
    meta_events=("PageView", "Lead"),
)


# --- interceptarea: ce e o cerere GA4 / Meta -------------------------------------------------


@pytest.mark.parametrize(
    ("url", "body", "expected"),
    [
        (f"{GA4}?v=2&tid=G-TEST123&en=page_view", None, ("ga4", ("page_view",), "G-TEST123")),
        (
            "https://www.google-analytics.com/g/collect?v=2&tid=G-X",
            "en=generate_lead&_et=1\nen=scroll",
            ("ga4", ("generate_lead", "scroll"), "G-X"),
        ),
        (f"{GA4}?tid=G-X&_en=purchase", None, ("ga4", ("purchase",), "G-X")),
        (f"{META}?id=987654&ev=PageView", None, ("meta", ("PageView",), "987654")),
        ("https://www.facebook.com/tr", "id=987654&ev=Lead", ("meta", ("Lead",), "987654")),
    ],
)
def test_collect_requests_are_classified_with_event_and_tag(
    url: str, body: str | None, expected: tuple[str, tuple[str, ...], str]
) -> None:
    hit = parse_collect_hit(url, body)

    assert hit is not None
    assert (hit.platform, hit.events, hit.tag_id) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.googletagmanager.com/gtag/js?id=G-TEST123",
        "https://connect.facebook.net/en_US/fbevents.js",
        "https://www.facebook.com/profile.php",
        "https://evil.example/g/collect?en=page_view",
        "not a url at all",
    ],
)
def test_loading_a_script_is_not_a_delivered_event(url: str) -> None:
    assert parse_collect_hit(url) is None


# --- verdictul contractului -------------------------------------------------------------------


def _record(
    *hits: CollectHit,
    status: int | None = 200,
    consent_found: bool = True,
    consent_clicked: bool = True,
    cta_found: bool | None = True,
    cta_clicked: bool | None = True,
) -> JourneyRecord:
    return JourneyRecord(
        status, None, consent_found, consent_clicked, cta_found, cta_clicked, list(hits)
    )


ALL_DELIVERED = (
    CollectHit("ga4", ("page_view",), "G-1", 204),
    CollectHit("ga4", ("generate_lead",), "G-1", 204),
    CollectHit("meta", ("PageView",), "1", 200),
    CollectHit("meta", ("Lead",), "1", 200),
)


def test_a_204_from_ga4_and_200_from_meta_pass_the_contract() -> None:
    verdict = evaluate_journey(CONTRACT, _record(*ALL_DELIVERED))

    assert verdict.failure_reason is None
    assert verdict.ga4 is not None and verdict.meta is not None
    assert (verdict.ga4.transport_ok, verdict.meta.transport_ok, verdict.journey_ok) == (
        True,
        True,
        True,
    )
    assert verdict.ga4.tag_id == "G-1"


@pytest.mark.parametrize(
    ("record", "reason", "ga4_ok"),
    [
        (_record(*ALL_DELIVERED, status=503), "SITE_UNAVAILABLE", None),
        (_record(*ALL_DELIVERED, status=None), "SITE_UNAVAILABLE", None),
        (
            _record(*ALL_DELIVERED, cta_found=False, cta_clicked=False),
            "CRITICAL_JOURNEY_BROKEN",
            True,
        ),
        (
            _record(
                CollectHit("ga4", ("page_view",), "G-1", 204),
                CollectHit("ga4", ("generate_lead",), "G-1", None, "net::ERR_CONNECTION_RESET"),
                *ALL_DELIVERED[2:],
            ),
            "NETWORK_FAILURE",
            False,
        ),
        (
            _record(
                CollectHit("ga4", ("page_view",), "G-1", 204),
                CollectHit("ga4", ("generate_lead",), "G-1", 500),
                *ALL_DELIVERED[2:],
            ),
            "NETWORK_FAILURE",
            False,
        ),
        (
            _record(CollectHit("ga4", ("page_view",), "G-1", 204), *ALL_DELIVERED[2:]),
            "EVENT_MISMATCH",
            False,
        ),
        (_record(*ALL_DELIVERED[2:]), "DATALAYER_MISSING", False),
        (_record(consent_clicked=False), "CONSENT_BLOCKED", None),
    ],
)
def test_every_failure_has_an_exact_reason(
    record: JourneyRecord, reason: str, ga4_ok: bool | None
) -> None:
    verdict = evaluate_journey(CONTRACT, record)

    assert verdict.failure_reason == reason
    assert (verdict.ga4.transport_ok if verdict.ga4 else None) == ga4_ok


def test_platforms_outside_the_contract_are_not_judged() -> None:
    contract = TrackingContract(url="https://autofix.ro/", ga4_events=("page_view",))

    verdict = evaluate_journey(contract, _record(CollectHit("ga4", ("page_view",), "G-1", 204)))

    assert (verdict.meta, verdict.journey_ok, verdict.failure_reason) == (None, None, None)


# --- contractul din Setari ----------------------------------------------------------------------


def _account(session: Session, **fields: Any) -> ClientAccount:
    account = _client_account(session)
    for name, value in fields.items():
        setattr(account, name, value)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_the_contract_comes_from_the_client_settings(session: Session) -> None:
    configured = _account(
        session,
        target_domain="https://autofix.ro",
        journey_path="/contact",
        journey_cta_selector="#contact-btn",
        journey_consent_selector="#accept",
        ga4_expected_events="page_view, generate_lead",
        meta_ad_account_id="act_1",
    )

    contract = contract_for(configured)

    assert contract == TrackingContract(
        url="https://autofix.ro/contact",
        cta_selector="#contact-btn",
        consent_selectors=("#accept", *DEFAULT_CONSENT_SELECTORS),
        ga4_events=("page_view", "generate_lead"),
        meta_events=("PageView",),
    )
    assert contract_for(_account(session)) is None


# --- pachetul de dovezi ---------------------------------------------------------------------------


def test_the_nightly_run_persists_an_evidence_bundle(session: Session) -> None:
    account = _account(
        session,
        target_domain="https://autofix.ro",
        journey_cta_selector="#contact-btn",
        ga4_expected_events="page_view, generate_lead",
    )

    async def recorder(contract: TrackingContract) -> JourneyRecord:
        return _record(
            CollectHit("ga4", ("page_view",), "G-1", 204),
            CollectHit("ga4", ("generate_lead",), "G-1", None, "net::ERR_FAILED"),
        )

    result = run_tracking_contract_job(client_account_id=account.id or 0, record=recorder)

    assert result == {
        "tested": True,
        "url": "https://autofix.ro/",
        "failure_reason": "NETWORK_FAILURE",
        "ga4_transport_ok": False,
        "meta_transport_ok": None,
    }
    [evidence] = session.exec(select(TrackingEvidence)).all()
    assert (evidence.navigation_status, evidence.cta_ok, evidence.ga4_transport_ok) == (
        200,
        True,
        False,
    )
    assert evidence.failure_reason == "NETWORK_FAILURE"
    assert evidence.evidence["hits"][1] == {
        "platform": "ga4",
        "events": ["generate_lead"],
        "tag_id": "G-1",
        "status": None,
        "failure": "net::ERR_FAILED",
    }
    assert evidence.evidence["verdict"]["ga4"]["expected_events"] == ["page_view", "generate_lead"]


def test_without_a_browser_or_a_domain_nothing_is_stored(session: Session) -> None:
    no_domain = _account(session)
    with_domain = _account(session, target_domain="https://autofix.ro")

    # ``record_journey`` e inlocuit in conftest cu unul care ridica ImportError, ca in API.
    assert run_tracking_contract_job(client_account_id=no_domain.id or 0) == {
        "tested": False,
        "reason": "fara domeniu in Setari",
    }
    assert run_tracking_contract_job(client_account_id=with_domain.id or 0)["tested"] is False
    assert session.exec(select(TrackingEvidence)).all() == []


def test_the_technician_reads_the_latest_evidence_and_the_last_two_speeds(
    session: Session,
) -> None:
    account = _account(session, target_domain="https://autofix.ro")
    now = datetime.now(tz=UTC)
    for days, lcp in ((9, 4700), (1, 4900), (20, 1500)):
        session.add(
            SiteSpeedSample(
                client_account_id=account.id or 0,
                url="https://autofix.ro/",
                lcp_ms=lcp,
                measured_at=now - timedelta(days=days),
            )
        )
    for hours, ok in ((30, True), (2, False)):
        session.add(
            TrackingEvidence(
                client_account_id=account.id or 0,
                url="https://autofix.ro/",
                started_at=now - timedelta(hours=hours),
                navigation_status=200,
                ga4_transport_ok=ok,
                failure_reason=None if ok else "NETWORK_FAILURE",
                evidence={"verdict": {"ga4": {"expected_events": ["page_view"]}}},
            )
        )
    session.commit()

    signals = DbTechnicalSignals(session).load(account.id or 0)

    assert signals.mobile_speed is not None and signals.previous_mobile_speed is not None
    assert (signals.mobile_speed.lcp_ms, signals.previous_mobile_speed.lcp_ms) == (4900, 4700)
    assert signals.evidence is not None
    assert (signals.evidence.ga4_ok, signals.evidence.ga4_events) == (False, ("page_view",))


# --- PageSpeed: mediana a 3 rulari ----------------------------------------------------------------


def test_three_pagespeed_runs_give_a_median_per_metric() -> None:
    def run(score: int, lcp: float, cls: float, tbt: float, field: float | None) -> dict[str, Any]:
        return {
            "performance_score": score, "lcp_ms": lcp, "cls": cls, "tbt_ms": tbt,
            "field_lcp_ms": field,
        }

    runs = [
        run(40, 5200.0, 0.3, 900.0, None),
        run(55, 3900.0, 0.1, 400.0, 3100.0),
        None,
        run(48, 4300.0, 0.2, 700.0, 3100.0),
    ]

    combined = median_pagespeed(runs)

    assert combined is not None
    assert (combined["runs"], combined["lcp_ms"], combined["cls"], combined["tbt_ms"]) == (
        3,
        4300.0,
        0.2,
        700.0,
    )
    assert (combined["performance_score"], combined["field_lcp_ms"]) == (48, 3100.0)
    assert median_pagespeed([None, None, None]) is None


def test_the_speed_sample_keeps_runs_and_field_data(session: Session) -> None:
    account = _account(session, target_domain="https://autofix.ro")

    def measure(url: str) -> dict[str, Any]:
        return {
            "runs": 3, "performance_score": 48, "lcp_ms": 4300.0, "cls": 0.2, "tbt_ms": 700.0,
            "field_lcp_ms": 3100.0, "field_cls": 0.12, "field_inp_ms": 240.0,
        }

    run_speed_check_job(client_account_id=account.id or 0, measure=measure)

    [sample] = session.exec(select(SiteSpeedSample)).all()
    assert (sample.runs, sample.lcp_ms) == (3, 4300)
    assert (sample.field_lcp_ms, sample.field_cls, sample.field_inp_ms) == (3100, 0.12, 240)


# --- scutul SSRF al browserului -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "public"),
    [
        ("postgres", False),
        ("localhost", False),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("169.254.169.254", False),
        ("::ffff:192.168.1.1", False),
        ("8.8.8.8", True),
    ],
)
def test_internal_hosts_are_never_public(host: str, public: bool) -> None:
    assert asyncio.run(synthetic._host_is_public(host, 443, {})) is public


def test_names_that_resolve_internally_or_not_at_all_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {"rebind.example": ["10.0.0.7"], "ok.example": ["93.184.216.34"]}

    async def resolve(host: str, port: int) -> list[str]:
        if host not in answers:
            raise OSError("NXDOMAIN")
        return answers[host]

    monkeypatch.setattr(synthetic, "resolve_host", resolve)
    cache: dict[str, bool] = {}

    assert asyncio.run(synthetic._host_is_public("rebind.example", 443, cache)) is False
    assert asyncio.run(synthetic._host_is_public("ok.example", 443, cache)) is True
    assert asyncio.run(synthetic._host_is_public("missing.example", 443, cache)) is False


def test_an_internal_start_url_never_reaches_the_browser() -> None:
    contract = TrackingContract(url="http://127.0.0.1:9/", ga4_events=("page_view",))

    record = asyncio.run(record_journey(contract))

    assert record.navigation_status is None
    assert record.navigation_error is not None and "SsrfBlockedError" in record.navigation_error
    assert evaluate_journey(contract, record).failure_reason == "SITE_UNAVAILABLE"


# --- Chromium real, pe un site local --------------------------------------------------------------

LOCAL_PLATFORMS = {"region1.google-analytics.com": 204, "www.facebook.com": 200}


@pytest.fixture(scope="module")
def chromium() -> None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Exception as exc:  # fara Playwright sau fara browser: se sare, nu pica
        pytest.skip(f"Chromium indisponibil: {exc}")


def _journey(body: bytes, *, status: int = 200) -> tuple[JourneyRecord, str | None]:
    with serve(body, status=status) as url:
        contract = TrackingContract(
            url=url,
            cta_selector="#contact-btn",
            ga4_events=("page_view", "generate_lead"),
            meta_events=("PageView", "Lead"),
        )
        record = asyncio.run(
            record_journey(contract, allow_private=True, fulfill=LOCAL_PLATFORMS)
        )
    return record, evaluate_journey(contract, record).failure_reason


@pytest.mark.usefixtures("chromium")
def test_a_real_browser_proves_the_events_reached_the_platforms() -> None:
    record, reason = _journey(page())

    assert reason is None
    assert record.navigation_status == 200
    assert (record.consent_clicked, record.cta_clicked) == (True, True)
    assert sorted((hit.platform, hit.events[0], hit.status) for hit in record.hits) == [
        ("ga4", "generate_lead", 204),
        ("ga4", "page_view", 204),
        ("meta", "Lead", 200),
        ("meta", "PageView", 200),
    ]


@pytest.mark.usefixtures("chromium")
@pytest.mark.parametrize(
    ("body", "status", "reason"),
    [
        (page(ga4_after_cta=False), 200, "EVENT_MISMATCH"),
        (page(cta_visible=False), 200, "CRITICAL_JOURNEY_BROKEN"),
        (page(), 503, "SITE_UNAVAILABLE"),
    ],
)
def test_a_real_browser_catches_each_broken_journey(body: bytes, status: int, reason: str) -> None:
    _, found = _journey(body, status=status)

    assert found == reason


# --- Setarile: contractul, validat ----------------------------------------------------------------

Signed = tuple[TestClient, FastAPI, dict[str, str], int]


@pytest.fixture
def settings_client(signed_in: Signed) -> Iterator[Signed]:  # noqa: F811
    yield signed_in


def test_the_contract_is_saved_from_settings(settings_client: Signed, session: Session) -> None:
    client, _, headers, account_id = settings_client

    response = client.patch(
        "/api/v1/me/site",
        headers=headers,
        json={
            "journey_path": "/contact",
            "journey_cta_selector": "#contact-btn",
            "ga4_expected_events": "page_view,generate_lead",
        },
    )

    assert response.status_code == 200, response.text
    account = session.get(ClientAccount, account_id)
    assert account is not None
    session.refresh(account)
    assert (account.journey_path, account.journey_cta_selector, account.ga4_expected_events) == (
        "/contact",
        "#contact-btn",
        "page_view, generate_lead",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"journey_path": "https://intern.local/"},
        {"journey_path": "//evil.example/"},
        {"ga4_expected_events": "page view"},
        {"meta_expected_events": ",".join(f"e{index}" for index in range(6))},
        {"journey_cta_selector": "#a\nb"},
    ],
)
def test_a_bad_contract_is_rejected(settings_client: Signed, payload: dict[str, str]) -> None:
    client, _, headers, _ = settings_client

    assert client.patch("/api/v1/me/site", headers=headers, json=payload).status_code == 422
