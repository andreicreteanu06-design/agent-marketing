"""Rutele Reginei: ``GET /client-message`` (mesajul CMO) si ``POST /chat`` (consiliul).

Ollama si Jev sunt MEREU simulati: fie clientii reali peste ``FakeOllama`` /
``FakeJev`` (``tests_server/llm_fakes.py`` - drumul complet, fara retea), fie absenti
(fara ``OLLAMA_HOST`` / ``JEV_API_KEY`` -> template si reguli fixe). Search Console e
o sursa falsa. Rutele trebuie sa raspunda 200 cu un mesaj utilizabil in orice situatie.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

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
    CHAIR_SYSTEM_PROMPT,
    CouncilEvent,
    CouncilListener,
    CouncilReply,
)
from ppc_agent_server.services.cpo import EFFORT_LEVELS, IMPACT_LEVELS
from ppc_agent_server.services.llm_client import LLMRouter
from ppc_agent_server.services.queen_agent import SearchSignal
from ppc_agent_server.services.queen_signals import DbFinancialSignals
from ppc_agent_server.settings import get_server_settings
from tests_server.llm_fakes import FakeJev, FakeOllama
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



@pytest.fixture
def signed_in(
    client: TestClient, agency_settings: Tenant, session: Session
) -> Iterator[tuple[TestClient, FastAPI, dict[str, str], int]]:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent()
    # Implicit (conftest): fara OLLAMA_HOST si fara JEV_API_KEY, oricare ar fi .env-ul.
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


def test_message_comes_from_the_local_model_when_ollama_is_configured(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    fake_ollama.reply = _LLM_ANSWER
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "llm"
    assert body["model"] == "llama3"
    assert body["message"] == _LLM_ANSWER
    assert body["fallback_reason"] is None
    assert body["directive_status"] == "ok"
    assert body["client_account_id"] == account_id

    [sent] = fake_ollama.requests
    system, user = (message["content"] for message in sent["messages"])
    assert "Senior AI Chief Marketing Officer" in system
    assert "«Ocupatul pragmatic»" in user
    assert "«Schimb ulei ATF cutie automata»" in user


def test_with_the_synthesis_off_the_cmo_message_skips_ollama(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    monkeypatch.setenv("USE_LLM_SYNTHESIS", "false")
    get_server_settings.cache_clear()
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    body = client.get(_URL, headers=headers).json()

    assert fake_ollama.requests == []
    assert body["source"] == "template" and "USE_LLM_SYNTHESIS" in body["fallback_reason"]
    assert "«Ocupatul pragmatic»" in body["message"]


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


@pytest.mark.parametrize("failure", ["error", "inventive"])
def test_a_failing_or_inventive_model_never_breaks_the_route(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
    failure: str,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    if failure == "error":
        fake_ollama.status = 500
    else:
        fake_ollama.reply = "Am dublat bugetul și vei avea 40% mai mulți clienți."
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(fake_ollama.requests) == 1
    assert body["source"] == "template"
    assert body["fallback_reason"]
    assert "bugetul" not in body["message"]
    assert "40%" not in body["message"]


def test_new_client_without_data_gets_the_standard_message(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], fake_ollama: FakeOllama
) -> None:
    client, app, headers, _ = signed_in
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent(
        [SearchSignal("autofix", "organic", 10, 2)]
    )

    response = client.get(_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["directive_status"] == "insufficient_data"
    assert body["source"] == "template"
    assert body["message"].startswith("Încă nu pot contura clientul tău ideal.")
    assert fake_ollama.requests == []  # fara client ideal, nu are ce explica un LLM


def test_route_requires_a_signed_in_client(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, _, _ = signed_in
    assert client.get(_URL).status_code == 401


# --- POST /api/v1/queen/chat - consiliul ------------------------------------------

_CHAT_URL = "/api/v1/queen/chat"
#: Singurul prompt care ajunge la Ollama: sinteza. Membrii vorbesc din date, fara model.
_COUNCIL_ANSWERS = {
    CHAIR_SYSTEM_PROMPT: (
        "Da, dar controlat: contul e rentabil - CPA 39,23 RON, sub ținta de 80 RON - deci "
        "cheltuiala poate crește treptat, doar pe ce aduce deja clienți, pentru "
        "«Ocupatul pragmatic». Orice creștere vine ca propunere pe care o aprobi tu."
    ),
}


def _council_ollama(fake: FakeOllama, chair: str | None = None) -> FakeOllama:
    """Ollama pentru consiliu: scrie sinteza Reginei, singurul apel al consiliului."""
    fake.replies = dict(_COUNCIL_ANSWERS)
    if chair is not None:
        fake.replies[CHAIR_SYSTEM_PROMPT] = chair
    return fake


def test_chat_reply_is_deliberated_by_the_council_through_the_local_model(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama).router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Merită să cresc bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == _COUNCIL_ANSWERS[CHAIR_SYSTEM_PROMPT]
    assert body["source"] == "llm"
    assert body["model"] == "llama3"
    assert body["topic"] == "budget"
    assert body["financial_status"] == "profitable"
    assert body["directive_status"] == "ok"
    assert body["ruling"]["decision"].startswith("Da, dar controlat")
    assert [opinion["member"] for opinion in body["opinions"]] == [
        "strategist",
        "cfo",
        "technician",
        "researcher",
        "cpo",
    ]
    # Membrii vorbesc din date, fara model: pozitiile lor sunt gata inainte de sinteza.
    assert all(opinion["source"] == "template" for opinion in body["opinions"])
    # Researcher-ul n-are date masurate (in teste, webul si Google Trends "pica"): spune
    # ce lipseste - si nu inventeaza nimic.
    assert body["opinions"][3]["fallback_reason"].startswith("Fără date")
    assert body["market"]["market_trend"]["direction"] == "unknown"
    assert not {"source", "is_demo"} & set(body["market"])
    assert body["ruling"]["market_context"] is None
    assert body["product"]["status"] == "fit"
    # O singura generare locala: sinteza. Fara Jev, mutarile CPO-ului pastreaza
    # estimarile fixe.
    assert len(fake_ollama.requests) == 1
    assert all(move["estimated_by"] == "fixed" for move in body["product"]["moves"])
    chair = fake_ollama.requests[-1]["messages"]
    assert chair[0]["content"] == CHAIR_SYSTEM_PROMPT
    assert "«Merită să cresc bugetul?»" in chair[1]["content"]
    assert "DECIZIA CONSILIULUI" in chair[1]["content"]


def test_with_the_synthesis_off_ollama_is_never_called(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    monkeypatch.setenv("USE_LLM_SYNTHESIS", "false")
    get_server_settings.cache_clear()
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama).router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Merită să cresc bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert fake_ollama.requests == []
    assert body["source"] == "template" and "USE_LLM_SYNTHESIS" in body["fallback_reason"]
    assert body["reply"].startswith("Da, dar controlat")


# --- chatul in flux (Server-Sent Events) ---------------------------------------------------

_SSE = {"Accept": "text/event-stream"}


def _events(text: str) -> list[tuple[str, Any]]:
    """Fluxul SSE -> ``(eveniment, date)``; comentariile (``: ...``) se sar."""
    events: list[tuple[str, Any]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


def _stream(
    client: TestClient, headers: dict[str, str], message: str
) -> tuple[str, list[tuple[str, Any]]]:
    response = client.post(_CHAT_URL, headers={**headers, **_SSE}, json={"message": message})
    assert response.status_code == 200, response.text
    return response.headers["content-type"], _events(response.text)


def test_chat_streams_the_deliberation_token_by_token(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama).router

    content_type, events = _stream(client, headers, "Merită să cresc bugetul?")

    assert content_type.startswith("text/event-stream")
    names = [name for name, _ in events]
    assert names[:2] == ["stage", "stage"]
    assert [data["stage"] for name, data in events if name == "stage"] == [
        "context",
        "deliberation",
        "synthesis",
    ]
    assert names[-2:] == ["reply", "done"]
    # Pozitiile membrilor pleaca imediat (sunt calculate din date), inainte de sinteza.
    opinions = [data["member"] for name, data in events if name == "opinion"]
    assert sorted(opinions) == ["cfo", "cpo", "researcher", "strategist", "technician"]
    assert names.index("token") > max(i for i, name in enumerate(names) if name == "opinion")
    # Tokenii sunt sinteza Reginei, cuvant cu cuvant; raspunsul final e acelasi text.
    tokens = [data["text"] for name, data in events if name == "token"]
    assert len(tokens) > 10
    assert "".join(tokens) == _COUNCIL_ANSWERS[CHAIR_SYSTEM_PROMPT]
    reply = events[-2][1]
    assert (reply["source"], reply["reply"]) == ("llm", _COUNCIL_ANSWERS[CHAIR_SYSTEM_PROMPT])
    # Acelasi raspuns ca varianta JSON: un CouncilReply intreg.
    assert CouncilReply.model_validate(reply).opinions


def test_a_rejected_draft_is_replaced_by_the_deterministic_reply(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    chair = "Dublează bugetul: vei avea 40% mai mulți clienți."
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama, chair).router

    _, events = _stream(client, headers, "Pot dubla bugetul?")

    # Ciorna a curs spre client...
    assert "".join(data["text"] for name, data in events if name == "token") == chair
    # ...dar raspunsul valabil e cel determinist, care o inlocuieste.
    reply = next(data for name, data in events if name == "reply")
    assert reply["source"] == "template"
    assert "40%" not in reply["reply"] and reply["reply"].startswith("Da, dar controlat")


def test_without_a_first_token_the_circuit_breaker_sends_the_deterministic_reply(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    fake_ollama.silent = True
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    _, events = _stream(client, headers, "Ce zici de TikTok?")

    assert not [name for name, _ in events if name == "token"]
    reply = next(data for name, data in events if name == "reply")
    assert reply["source"] == "template"
    assert reply["reply"].startswith("Se poate testa TikTok, dar ca experiment mic")
    # Singurul apel e sinteza: fara niciun token, pleaca raspunsul determinist.
    assert fake_ollama.connections == 1
    assert all(
        data["source"] == "template" for name, data in events if name == "opinion"
    )


def test_without_a_voice_the_stream_still_ends_with_a_reply(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    _seed(session, account_id)

    _, events = _stream(client, headers, "E rentabilă campania?")

    names = [name for name, _ in events]
    assert "token" not in names and names[-2:] == ["reply", "done"]
    assert events[-2][1]["source"] == "template"


def test_the_stream_is_rate_limited_before_it_starts(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    for _ in range(6):
        client.post(_CHAT_URL, headers={**headers, **_SSE}, json={"message": "Salut"})

    response = client.post(_CHAT_URL, headers={**headers, **_SSE}, json={"message": "Salut"})

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")


def test_a_long_deliberation_keeps_the_connection_alive() -> None:
    def slow(on_event: CouncilListener) -> CouncilReply:
        on_event(CouncilEvent("stage", stage="deliberation"))
        time.sleep(0.2)
        raise RuntimeError("baza de date a picat")

    chunks = list(queen.council_event_stream(slow, keepalive=0.02))

    assert any(chunk.startswith(": ") for chunk in chunks)  # comentariu SSE, nu eveniment
    assert [name for name, _ in _events("".join(chunks))] == ["stage", "error", "done"]
    error = _events("".join(chunks))[1][1]
    assert error == {"detail": queen.STREAM_ERROR}


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
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    chair = "Dublează bugetul: vei avea 40% mai mulți clienți."
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama, chair).router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Pot dubla bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(fake_ollama.requests) == 1
    assert body["source"] == "template"
    assert "40%" not in body["reply"]
    assert body["reply"].startswith("Da, dar controlat")


def test_a_failing_local_model_still_gets_an_answer(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    fake_ollama.status = 500
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Ce zici de TikTok?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(fake_ollama.requests) == 1
    assert body["source"] == "template"
    assert body["topic"] == "channel"
    assert body["reply"].startswith("Se poate testa TikTok, dar ca experiment mic")
    assert all(opinion["source"] == "template" for opinion in body["opinions"])


def test_ollama_not_running_falls_back_without_waiting_on_every_call(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    fake_ollama.down = True
    app.dependency_overrides[queen.get_llm_router] = fake_ollama.router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Ce zici de TikTok?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "template"
    assert "LLMUnavailableError" in body["fallback_reason"]
    assert body["reply"].startswith("Se poate testa TikTok, dar ca experiment mic")
    assert all(opinion["source"] == "template" for opinion in body["opinions"])
    # Doar sinteza a incercat: o singura conexiune refuzata.
    assert fake_ollama.connections == 1


def test_jev_scores_the_cpo_moves_and_ollama_writes_the_answer(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
    session: Session,
    fake_jev: FakeJev,
    fake_ollama: FakeOllama,
) -> None:
    client, app, headers, account_id = signed_in
    _seed(session, account_id)
    # Impact "High" (2), efort "A few days" (0,5), ambele sigure.
    fake_jev.score_rule = lambda state, qid: (3.0, 0.9) if qid.startswith("impact") else (0.0, 0.9)
    router = LLMRouter(jev=fake_jev.client(), ollama=_council_ollama(fake_ollama).client())
    app.dependency_overrides[queen.get_llm_router] = lambda: router

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Merită să cresc bugetul?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "llm"
    [move] = body["product"]["moves"]
    assert (move["kind"], move["estimated_by"]) == ("message", "jev")
    assert (move["impact"], move["effort"]) == (IMPACT_LEVELS[3][1], EFFORT_LEVELS[0][1])
    # O singura cerere Jev (cautarea pe web e offline in teste, deci nimic de verificat).
    [scored] = fake_jev.requests
    assert set(scored["questions"]) == {"impact_0", "effort_0"}
    assert scored["state"]["moves"][0]["description"].startswith("rescrierea mesajului")
    assert len(fake_ollama.requests) == 1


def test_new_client_gets_no_generic_llm_advice(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], fake_ollama: FakeOllama
) -> None:
    client, app, headers, _ = signed_in
    app.dependency_overrides[queen.get_llm_router] = _council_ollama(fake_ollama).router
    app.dependency_overrides[queen.get_seo_intent] = lambda: _FakeSeoIntent(
        [SearchSignal("autofix", "organic", 10, 2)]
    )

    response = client.post(_CHAT_URL, headers=headers, json={"message": "Cât buget să pun?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert fake_ollama.requests == []
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
