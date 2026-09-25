"""``GET /api/v1/queen/client-message`` - mesajul CMO al Reginei catre client.

Hugging Face e MEREU simulat: fie un ``HuggingFaceChatClient`` real peste un
``httpx.MockTransport`` (drumul complet, fara retea), fie absent (fara cheie ->
template). Search Console e o sursa falsa. Ruta trebuie sa raspunda 200 cu un
mesaj utilizabil in orice situatie.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.routers import queen
from ppc_agent_server.services.hf_client import HuggingFaceChatClient, hf_client_from_settings
from ppc_agent_server.services.queen_agent import SearchSignal
from ppc_agent_server.settings import ServerSettings
from tests_server.test_brand_alignment import (
    _FakeSeoIntent,
    _seed_meta_launch,
    _seed_paid_terms,
)

_URL = "/api/v1/queen/client-message"
_LLM_ANSWER = (
    "Am observat că publicul tău ideal este «Ocupatul pragmatic», care vrea să rezolve "
    "totul din telefon. Reclama «Schimb ulei ATF cutie automata» vorbește tehnic, deși "
    "CPA-ul ei de 68,89 RON e sub ținta de 80 RON. Am propus rescrierea ei pe timp salvat; "
    "totul așteaptă aprobarea ta."
)


class _HuggingFaceMock:
    """Routerul Hugging Face simulat: tine minte cererile, raspunde ce i se spune."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": _LLM_ANSWER}}]}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response

    def client(self) -> HuggingFaceChatClient:
        return HuggingFaceChatClient(
            api_key="hf_test", model="test/cmo", transport=httpx.MockTransport(self)
        )


@pytest.fixture
def signed_in(
    client: TestClient, agency_settings: Tenant, session: Session
) -> Iterator[tuple[TestClient, FastAPI, dict[str, str], int]]:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent()
    # Implicit: nicio cheie Hugging Face, oricare ar fi .env-ul masinii de test.
    app.dependency_overrides[queen.get_cmo_voice] = lambda: hf_client_from_settings(
        ServerSettings(huggingface_api_key="")
    )
    token = client.post(
        "/api/v1/signup",
        json={"name": "Autofix", "email": "client@autofix.ro", "password": "parola-sigura-123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = int(client.get("/api/v1/me", headers=headers).json()["account"]["id"])
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.brand_name = "autofix"
    session.add(account)
    session.commit()
    yield client, app, headers, account_id
    app.dependency_overrides.clear()


def _seed(session: Session, account_id: int) -> None:
    _seed_paid_terms(session, account_id)
    _seed_meta_launch(session, account_id)


def test_message_comes_from_hugging_face_when_a_key_is_configured(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    hf = _HuggingFaceMock()
    app.dependency_overrides[queen.get_cmo_voice] = hf.client

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "llm"
    assert body["model"] == "test/cmo"
    assert body["message"] == _LLM_ANSWER
    assert body["fallback_reason"] is None
    assert body["directive_status"] == "ok"
    assert body["client_account_id"] == account_id

    [request] = hf.requests
    assert request.url.host == "router.huggingface.co"
    sent = json.loads(request.content)
    system, user = (message["content"] for message in sent["messages"])
    assert "Senior AI Chief Marketing Officer" in system
    assert "«Ocupatul pragmatic»" in user
    assert "«Schimb ulei ATF cutie automata»" in user


def test_without_a_key_the_route_answers_from_the_template(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    _seed(session, account_id)

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "template"
    assert body["model"] is None
    assert "nu e configurată" in body["fallback_reason"]
    assert "«Ocupatul pragmatic»" in body["message"]
    assert "Reclama «Schimb ulei ATF cutie automata» nu rezonează cu el" in body["message"]


@pytest.mark.parametrize(
    "hf_response",
    [
        httpx.Response(503, json={"error": "Model is overloaded"}),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Am dublat bugetul și vei avea 40% mai mulți clienți."}}
                ]
            },
        ),
    ],
)
def test_a_failing_or_inventive_model_never_breaks_the_route(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    hf_response: httpx.Response,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    hf = _HuggingFaceMock(hf_response)
    app.dependency_overrides[queen.get_cmo_voice] = hf.client

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(hf.requests) == 1
    assert body["source"] == "template"
    assert body["fallback_reason"]
    assert "bugetul" not in body["message"]
    assert "40%" not in body["message"]


def test_new_client_without_data_gets_the_standard_message(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, app, headers, _ = signed_in
    hf = _HuggingFaceMock()
    app.dependency_overrides[queen.get_cmo_voice] = hf.client
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent(
        [SearchSignal("autofix", "organic", 10, 2)]
    )

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["directive_status"] == "insufficient_data"
    assert body["source"] == "template"
    assert body["message"].startswith("Încă nu pot contura clientul tău ideal.")
    assert hf.requests == []  # fara client ideal, nu are ce explica un LLM


def test_route_requires_a_signed_in_client(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, _, _ = signed_in
    assert client.get(_URL).status_code == 401
