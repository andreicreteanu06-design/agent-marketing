"""Endpoint-urile de audit: start / stare / rezultate.

Motorul de audit e inlocuit cu unul fals prin ``dependency_overrides`` (acelasi
tipar ca ``_build_llm_client``/``_get_auto_fetcher``), deci testele verifica
CONTRACTUL HTTP - autentificare, coduri de stare, izolarea intre clienti - nu
crawl-ul, care are testele lui in ``test_audit_service.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from seo_geo_agent import router as router_module
from seo_geo_agent.app import create_app
from seo_geo_agent.audit import url_policy
from seo_geo_agent.audit.scoring import PillarScore
from seo_geo_agent.audit.service import AuditConfig, AuditProgress, AuditResult
from seo_geo_agent.audit.store import AuditStore
from tests_seo_geo.conftest import make_token

_OTHER_CLIENT_ID = 99


def _fake_result() -> AuditResult:
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
        pages=[],
        issues=[],
        scores={
            "seo": PillarScore(88, 10, 1, 20.0, 2.0),
            "geo": PillarScore(61, 6, 2, 12.0, 4.0),
        },
    )


@pytest.fixture
def audit_client(
    jwt_settings: None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, AuditStore]]:
    """Client HTTP cu registru propriu, motor fals si fara rezolvare DNS."""

    async def _no_dns(_hostname: str) -> bool:
        return False

    monkeypatch.setattr(url_policy, "_resolves_to_blocked_address", _no_dns)

    async def _fake_runner(
        _start_url: str, _config: AuditConfig, on_progress: Callable[[AuditProgress], None]
    ) -> AuditResult:
        on_progress(AuditProgress(crawled=3, queued=0, max_pages=_config.max_pages))
        return _fake_result()

    store = AuditStore()
    app = create_app()
    app.dependency_overrides[router_module._get_audit_runner] = lambda: _fake_runner
    app.dependency_overrides[router_module._get_audit_store] = lambda: store
    with TestClient(app) as client:
        yield client, store


def _wait_for_completion(client: TestClient, audit_id: str, headers: dict[str, str]) -> str:
    """Interogheaza starea pana cand auditul nu mai ruleaza (motorul fals e instant)."""
    for _ in range(20):
        status = client.get(f"/api/v1/seo-geo/audit/{audit_id}", headers=headers).json()
        if status["status"] != "running":
            return str(status["status"])
    raise AssertionError("auditul fals nu s-a terminat")


def test_auditul_cere_autentificare() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/seo-geo/audit", json={"domain": "exemplu.ro"})
    assert response.status_code == 401


def test_pornirea_intoarce_202_si_un_id(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, _ = audit_client
    response = client.post(
        "/api/v1/seo-geo/audit", json={"domain": "exemplu.ro"}, headers=auth_headers
    )
    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["audit_id"]


def test_domeniul_intern_e_refuzat_inainte_sa_porneasca_ceva(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, store = audit_client
    response = client.post(
        "/api/v1/seo-geo/audit", json={"domain": "http://127.0.0.1:8000/"}, headers=auth_headers
    )
    assert response.status_code == 422
    assert store.get(0, "oricare") is None


def test_rezultatele_ajung_la_client_dupa_ce_auditul_se_termina(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, _ = audit_client
    audit_id = client.post(
        "/api/v1/seo-geo/audit", json={"domain": "exemplu.ro"}, headers=auth_headers
    ).json()["audit_id"]
    assert _wait_for_completion(client, audit_id, auth_headers) == "completed"

    results = client.get(f"/api/v1/seo-geo/audit/{audit_id}/results", headers=auth_headers)
    assert results.status_code == 200
    body = results.json()
    assert body["seo"]["score"] == 88
    assert body["geo"]["score"] == 61
    assert body["summary"]["completed"] is True


def test_rezultatele_cerute_prea_devreme_dau_409(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, store = audit_client
    record = store.create(client_id=42, domain="exemplu.ro")
    response = client.get(
        f"/api/v1/seo-geo/audit/{record.audit_id}/results", headers=auth_headers
    )
    assert response.status_code == 409


def test_un_client_nu_vede_auditul_altuia(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    """Un id ghicit nu trebuie sa dea niciodata raportul altcuiva."""
    client, store = audit_client
    foreign = store.create(client_id=_OTHER_CLIENT_ID, domain="alt-client.ro")
    response = client.get(f"/api/v1/seo-geo/audit/{foreign.audit_id}", headers=auth_headers)
    assert response.status_code == 404


def test_al_doilea_audit_simultan_e_refuzat(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, store = audit_client
    store.create(client_id=42, domain="exemplu.ro")
    response = client.post(
        "/api/v1/seo-geo/audit", json={"domain": "exemplu.ro"}, headers=auth_headers
    )
    assert response.status_code == 429


def test_max_pages_e_validat_de_schema(
    audit_client: tuple[TestClient, AuditStore], auth_headers: dict[str, str]
) -> None:
    client, _ = audit_client
    response = client.post(
        "/api/v1/seo-geo/audit",
        json={"domain": "exemplu.ro", "max_pages": 5000},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_tokenul_altui_secret_e_respins(audit_client: tuple[TestClient, AuditStore]) -> None:
    client, _ = audit_client
    headers = {"Authorization": f"Bearer {make_token(secret='alt-secret')}"}
    response = client.post("/api/v1/seo-geo/audit", json={"domain": "exemplu.ro"}, headers=headers)
    assert response.status_code == 401
