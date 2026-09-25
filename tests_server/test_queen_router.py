"""Rutele Reginei: ``GET /client-message`` (mesajul CMO) si ``POST /chat`` (consiliul).

Hugging Face e MEREU simulat: fie un ``HuggingFaceChatClient`` real peste un
``httpx.MockTransport`` (drumul complet, fara retea), fie absent (fara cheie ->
template). Search Console e o sursa falsa. Rutele trebuie sa raspunda 200 cu un
mesaj utilizabil in orice situatie.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    SearchTermConversion,
    Tenant,
)
from ppc_agent_server.routers import queen
from ppc_agent_server.services.council import (
    CFO_SYSTEM_PROMPT,
    CHAIR_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
)
from ppc_agent_server.services.hf_client import HuggingFaceChatClient, hf_client_from_settings
from ppc_agent_server.services.queen_agent import SearchSignal
from ppc_agent_server.services.queen_signals import DbFinancialSignals
from ppc_agent_server.services.technician import TECHNICIAN_SYSTEM_PROMPT
from ppc_agent_server.settings import ServerSettings
from tests_server.test_brand_alignment import (
    TECHNICAL_HEADLINE,
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
    assert "Reclama «Schimb ulei ATF cutie automata» nu îi vorbește" in body["message"]


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


# --- POST /api/v1/queen/chat - consiliul ------------------------------------------

_CHAT_URL = "/api/v1/queen/chat"
_COUNCIL_ANSWERS = {
    STRATEGIST_SYSTEM_PROMPT: (
        "Clientul tău ideal e «Ocupatul pragmatic»: vrea să rezolve totul din telefon."
    ),
    CFO_SYSTEM_PROMPT: "Contul e rentabil: CPA-ul e 39,23 RON, sub ținta de 80 RON.",
    TECHNICIAN_SYSTEM_PROMPT: "Tracking: verde. Conversiile Google Ads ajung.",
    CHAIR_SYSTEM_PROMPT: (
        "Da, dar controlat: contul e rentabil - CPA 39,23 RON, sub ținta de 80 RON - deci "
        "cheltuiala poate crește treptat, doar pe ce aduce deja clienți, pentru "
        "«Ocupatul pragmatic». Orice creștere vine ca propunere pe care o aprobi tu."
    ),
}


class _CouncilHuggingFace:
    """Routerul Hugging Face pentru consiliu: raspunde dupa promptul de sistem primit."""

    def __init__(self, chair: str | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.answers = dict(_COUNCIL_ANSWERS)
        if chair is not None:
            self.answers[CHAIR_SYSTEM_PROMPT] = chair

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        system = json.loads(request.content)["messages"][0]["content"]
        content = self.answers[system]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def client(self) -> HuggingFaceChatClient:
        return HuggingFaceChatClient(
            api_key="hf_test", model="test/council", transport=httpx.MockTransport(self)
        )


def test_chat_reply_is_deliberated_by_the_council_through_hugging_face(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    hf = _CouncilHuggingFace()
    app.dependency_overrides[queen.get_cmo_voice] = hf.client

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Merită să cresc bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == _COUNCIL_ANSWERS[CHAIR_SYSTEM_PROMPT]
    assert body["source"] == "llm"
    assert body["model"] == "test/council"
    assert body["topic"] == "budget"
    assert body["financial_status"] == "profitable"
    assert body["directive_status"] == "ok"
    assert body["ruling"]["decision"].startswith("Da, dar controlat")
    assert [(opinion["member"], opinion["source"]) for opinion in body["opinions"]] == [
        ("strategist", "llm"),
        ("cfo", "llm"),
        ("technician", "llm"),
    ]
    # Patru apeluri: cei trei membri, apoi sinteza - toate catre routerul HF simulat.
    assert len(hf.requests) == 4
    assert {request.url.host for request in hf.requests} == {"router.huggingface.co"}
    chair = json.loads(hf.requests[-1].content)["messages"]
    assert chair[0]["content"] == CHAIR_SYSTEM_PROMPT
    assert "«Merită să cresc bugetul?»" in chair[1]["content"]
    assert "DECIZIA CONSILIULUI" in chair[1]["content"]


def test_chat_without_a_key_answers_from_the_deterministic_council(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    _seed(session, account_id)

    response = client.post(_CHAT_URL, headers=headers, json={"message": "E rentabilă campania?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "template"
    assert body["model"] is None
    assert "nu e configurată" in body["fallback_reason"]
    assert body["reply"].startswith(
        "Contul e rentabil: CPA-ul e 39,23 RON (26 de conversii din 1020 RON cheltuiți), "
        "sub ținta de 80 RON."
    )
    assert body["reply"].endswith("Nimic nu se aplică fără aprobarea ta.")


def test_an_inventive_council_never_reaches_the_client(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    hf = _CouncilHuggingFace(chair="Dublează bugetul: vei avea 40% mai mulți clienți.")
    app.dependency_overrides[queen.get_cmo_voice] = hf.client

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Pot dubla bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(hf.requests) == 4
    assert body["source"] == "template"
    assert "40%" not in body["reply"]
    assert body["reply"].startswith("Da, dar controlat")


def test_hugging_face_down_still_gets_an_answer(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    hf = _HuggingFaceMock(httpx.Response(503, json={"error": "Model is overloaded"}))
    app.dependency_overrides[queen.get_cmo_voice] = hf.client

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Ce zici de TikTok?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(hf.requests) == 4
    assert body["source"] == "template"
    assert body["topic"] == "channel"
    assert body["reply"].startswith("Se poate testa TikTok, dar ca experiment mic")
    assert all(opinion["source"] == "template" for opinion in body["opinions"])


def test_new_client_gets_no_generic_llm_advice(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, app, headers, _ = signed_in
    hf = _CouncilHuggingFace()
    app.dependency_overrides[queen.get_cmo_voice] = hf.client
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent(
        [SearchSignal("autofix", "organic", 10, 2)]
    )

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Cât buget să pun?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert hf.requests == []
    assert body["financial_status"] == "insufficient_data"
    assert body["reply"].startswith("Încă nu am destule date ca să-ți răspund pe cifre")


@pytest.mark.parametrize("payload", [{"message": "   "}, {"message": "x" * 1001}, {}])
def test_chat_rejects_blank_or_oversized_questions(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], payload: dict[str, str]
) -> None:
    client, _, headers, _ = signed_in
    assert client.post(_CHAT_URL, headers=headers, json=payload).status_code == 422


def test_chat_requires_a_signed_in_client(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, _, _ = signed_in
    assert client.post(_CHAT_URL, json={"message": "Salut"}).status_code == 401


def test_financial_signals_come_from_the_database(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    _, _, _, account_id = signed_in
    _seed(session, account_id)
    session.add(
        ProposedChange(
            client_account_id=account_id,
            op=ChangeOp.UPDATE,
            resource="meta_ad/120001",
            resource_type="ad_copy",
            rationale="[Regina] rescriere",
            source_module="queen_agent",
            status=ChangeStatus.PENDING,
        )
    )
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=datetime.now(tz=UTC) - timedelta(days=2),
            search_term="service cutie automata pret",
            clicks=5,
            impressions=50,
            cost=Decimal("20"),
            conversions=1.0,
            conversions_value=Decimal("300"),
        )
    )
    session.commit()

    signals = DbFinancialSignals(session).load(account_id)

    [ad] = signals.ads
    assert (ad.ad_id, ad.label, ad.spend, ad.conversions, ad.target_cpa) == (
        "120001",
        TECHNICAL_HEADLINE,
        Decimal("620"),
        9,
        Decimal("80"),
    )
    terms = {term.term: term for term in signals.search_terms}
    # Agregat pe termen, iar randul de acum 90 de zile e in afara ferestrei.
    assert "service cutie automata non stop" not in terms
    price = terms["service cutie automata pret"]
    assert (price.cost, price.conversions, price.value) == (Decimal("120"), 4.0, Decimal("300"))
    assert signals.pending_proposals == 1
    assert signals.daily_spend_cap == Decimal("50.00")
    assert signals.objective == "lead_generation"
