"""Interviul din chat inaintea primei campanii: costurile, zona, raza - si lansarea pe ea.

Harta e inlocuita (fara OpenStreetMap). Raspunsurile sunt scrise cum le-ar scrie un om:
cu "lei", virgule, "3 din 10", "nu stiu".
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent_server.models import ClientAccount, ProposedChange, Tenant
from ppc_agent_server.routers.client_auth import get_geocoder
from ppc_agent_server.services.avatar_builder import (
    PROFILE_KEYS,
    CustomerAvatar,
    avatar_from_answers,
)
from ppc_agent_server.services.client_intake import parse_number, parse_share, plain
from ppc_agent_server.services.geocoding import Place
from tests_server.test_campaign_launch import _request, _signup

_CHAT = "/api/v1/queen/chat"
_CLUJ = Place(
    latitude=Decimal("46.770439"),
    longitude=Decimal("23.591423"),
    label="Strada Memorandumului 28, Cluj-Napoca",
    locality="Cluj-Napoca",
    size="oras_mare",
)


class _Map:
    """Harta de test: gaseste doar adresele care contin "Cluj"."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def __call__(self, address: str, country: str) -> Place | None:
        self.asked.append((address, country))
        return _CLUJ if "cluj" in address.lower() else None


@pytest.fixture
def chat(
    client: TestClient, agency_settings: Tenant, session: Session
) -> Iterator[tuple[TestClient, dict[str, str], int, _Map]]:
    the_map = _Map()
    client.app.dependency_overrides[get_geocoder] = lambda: the_map  # type: ignore[attr-defined]
    headers, account_id = _signup(client)
    yield client, headers, account_id, the_map
    client.app.dependency_overrides.pop(get_geocoder, None)  # type: ignore[attr-defined]


def _say(client: TestClient, headers: dict[str, str], message: str) -> str:
    response = client.post(_CHAT, headers=headers, json={"message": message})
    assert response.status_code == 200, response.text
    reply: str = response.json()["reply"]
    return reply


def _shop(session: Session, account_id: int) -> ClientAccount:
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.objective = CampaignObjective.SALES
    session.add(account)
    session.commit()
    return account


def test_a_shop_interview_ends_with_its_profit_threshold_and_a_local_radius(
    chat: tuple[TestClient, dict[str, str], int, _Map], session: Session
) -> None:
    client, headers, account_id, the_map = chat
    _shop(session, account_id)

    first = _say(client, headers, "Vreau să lansez prima campanie")
    assert first.startswith("Înainte de prima campanie")
    assert first.endswith("Care e valoarea medie a unei comenzi, în lei, cu TVA?")
    _say(client, headers, "250 lei")
    _say(client, headers, "110")
    _say(client, headers, "18 lei")
    _say(client, headers, "2%")
    area = _say(client, headers, "5")
    assert area.startswith("Unde sunt clienții tăi?")
    _say(client, headers, "1")
    missing = _say(client, headers, "strada principala 3")
    assert missing.startswith("Nu am găsit adresa pe hartă")
    kind = _say(client, headers, "Str. Memorandumului 28, Cluj-Napoca")
    assert kind.startswith("Ce fel de afacere e?")
    _say(client, headers, "o cafenea")
    done = _say(client, headers, "până la 10 km")

    assert "o afacere la care oamenii vin des" in done
    assert "Ai fi mers până la 10 km, dar încep cu 3" in done
    assert "CAC-ul maxim e 110 lei" in done
    assert "ROAS-ul minim e 2,28" in done
    assert "pe o rază de 3 km în jurul adresei Strada Memorandumului 28" in done
    session.expire_all()
    account = session.get(ClientAccount, account_id)
    assert account is not None
    assert account.economics_confirmed_at is not None
    assert account.min_roas == Decimal("2.28")
    assert account.default_lead_value == Decimal("250.00")
    assert account.target_radius_km == Decimal("3")
    # Dupa cifre, clientul ideal: prima intrebare JTBD asteapta deja in chat.
    assert done.endswith("Ce se întâmplă în viața clientului tău chiar înainte să te caute?")
    assert account.intake_step == "customer_situation"
    assert the_map.asked[-1] == ("str. memorandumului 28, cluj napoca", "RO")


def test_an_unclear_answer_is_asked_again_and_why_is_explained(
    chat: tuple[TestClient, dict[str, str], int, _Map],
) -> None:
    client, headers, _, _ = chat
    _say(client, headers, "Când lansăm?")

    again = _say(client, headers, "depinde")
    assert again.startswith("Nu am înțeles răspunsul - de exemplu «600 lei».")
    why = _say(client, headers, "De ce ai nevoie de asta?")
    assert why.startswith("Atât poți plăti, cel mult, ca să câștigi un client")


def test_a_lead_business_selling_nationwide_and_a_cancel_that_keeps_answers(
    chat: tuple[TestClient, dict[str, str], int, _Map], session: Session
) -> None:
    client, headers, account_id, _ = chat
    _say(client, headers, "Vreau o campanie nouă")
    _say(client, headers, "600 lei")
    stopped = _say(client, headers, "anulează")
    assert stopped.startswith("Bine, ne oprim aici")
    # Dupa anulare, chatul merge din nou la consiliu - interviul nu-l mai ocupa.
    assert not _say(client, headers, "Ce zici de TikTok?").startswith("Din 10 cereri")

    assert _say(client, headers, "Vreau să lansez").endswith(
        "Din 10 cereri primite (formulare, apeluri), câte devin clienți?"
    )
    _say(client, headers, "3 din 10")
    done = _say(client, headers, "2")
    assert "o cerere valorează 180 lei" in done
    assert "Reclamele merg în toată țara." in done
    session.expire_all()
    account = session.get(ClientAccount, account_id)
    assert account is not None
    assert account.default_lead_value == Decimal("180.00")
    assert account.min_roas is None


def test_the_first_launch_waits_for_the_interview_then_targets_the_radius(
    chat: tuple[TestClient, dict[str, str], int, _Map],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, account_id, _ = chat
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.meta_ad_account_id = "act_555"
    session.add(account)
    session.commit()

    blocked = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())
    assert blocked.status_code == 409
    assert "prima: Cât câștigi, după costurile tale" in blocked.json()["detail"]
    # Intrebarea asteapta deja in chat: primul mesaj e raspunsul ei.
    _say(client, headers, "800")
    _say(client, headers, "4 din 10")
    _say(client, headers, "local")
    _say(client, headers, "Str. Memorandumului 28, Cluj")
    _say(client, headers, "service auto")
    done = _say(client, headers, "nu știu")
    # Service auto intr-un oras mare, fara limita de la client: alege consiliul.
    assert done.startswith("Pentru o afacere cu programări într-un oraș mare, clienții vin")
    assert "rază de 6 km în jurul adresei" in done
    assert _say(client, headers, "raza 8 km").startswith("Am schimbat raza la 8 km")
    # Clientul ideal si oferta: "nu știu" e un răspuns bun - nu blochează lansarea.
    for _ in PROFILE_KEYS:
        last = _say(client, headers, "nu știu")
    assert last.startswith("Gata, am tot ce-mi trebuie. Despre clienții tăi nu știm încă multe")

    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())

    assert response.status_code == 201, response.text
    proposal = session.get(ProposedChange, response.json()["id"])
    assert proposal is not None
    assert proposal.after["location"] == {
        "latitude": "46.770439",
        "longitude": "23.591423",
        "radius_km": "8.00",
    }
    economics: dict[str, Any] = proposal.before["economics"]
    assert economics["max_cac"] == "800.00"
    assert economics["max_cpl"] == "320.00"
    assert "o raza de 8.00 km in jurul afacerii" in proposal.rationale
    assert "Campania e profitabilă cât timp un client costă sub 800 lei" in proposal.rationale


def test_the_ideal_customer_interview_builds_the_jtbd_avatar_in_the_clients_words(
    chat: tuple[TestClient, dict[str, str], int, _Map], session: Session
) -> None:
    """Un client vechi, cu cifrele deja date: la lansare, consiliul intreaba doar de clienti."""
    client, headers, account_id, _ = chat
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.customer_profit = Decimal("600")
    account.close_rate_pct = Decimal("30")
    account.service_area = "national"
    account.economics_confirmed_at = datetime.now(tz=UTC)
    session.add(account)
    session.commit()

    first = _say(client, headers, "Vreau să lansez prima campanie")
    assert first.startswith("Înainte de prima campanie, consiliul vrea să-ți cunoască clienții")
    assert first.endswith("Ce se întâmplă în viața clientului tău chiar înainte să te caute?")
    _say(client, headers, "I s-a stricat mașina și pleacă în concediu peste o săptămână")
    _say(client, headers, "mașina reparată până vineri")
    _say(client, headers, "să plece liniștit la drum")
    _say(client, headers, "liniștit")
    _say(client, headers, "nu contează")
    why = _say(client, headers, "De ce întrebi?")
    assert why.startswith("Bariera cea mai mare decide ce testăm primul")
    _say(client, headers, "prețul; și că nu știe dacă lucrarea iese bine?")
    _say(client, headers, "merge la service-ul de lângă bloc")
    unclear = _say(client, headers, "multe")
    assert unclear.startswith("Nu am înțeles răspunsul - de exemplu «3», sau «unul singur»")
    _say(client, headers, "cinci pachete")
    done = _say(client, headers, "nu oferim")

    assert done.startswith(
        "Gata, am tot ce-mi trebuie. Clientul ideal, în cuvintele afacerii (Jobs to Be Done) - "
        "situația: «I s-a stricat mașina și pleacă în concediu peste o săptămână»"
    )
    assert "Oferta: 5 pachete, fără garanție." in done
    session.expire_all()
    account = session.get(ClientAccount, account_id)
    assert account is not None and account.intake_step == ""
    assert avatar_from_answers(account.avatar_answers) == CustomerAvatar(
        customer_situation="I s-a stricat mașina și pleacă în concediu peste o săptămână",
        functional_job="mașina reparată până vineri",
        desired_progress="să plece liniștit la drum",
        emotional_job="liniștit",
        anxieties=["prețul", "că nu știe dacă lucrarea iese bine?"],
        switching_cost="merge la service-ul de lângă bloc",
    )
    assert account.avatar_answers is not None
    assert account.avatar_answers["offer_options"] == 5
    assert account.avatar_answers["risk_reversal"] == ""


def test_the_form_gives_the_same_thresholds_and_refuses_a_losing_shop(
    chat: tuple[TestClient, dict[str, str], int, _Map], session: Session
) -> None:
    client, headers, account_id, _ = chat
    _shop(session, account_id)
    losing = client.put(
        "/api/v1/me/economics",
        headers=headers,
        json={
            "average_order_value": 100,
            "product_cost": 90,
            "shipping_cost": 15,
            "payment_fee_pct": 0,
            "return_rate_pct": 0,
            "service_area": "national",
        },
    )
    assert losing.status_code == 422
    assert "nu lasă profit" in losing.json()["detail"]

    response = client.put(
        "/api/v1/me/economics",
        headers=headers,
        json={
            "average_order_value": 250,
            "product_cost": 110,
            "shipping_cost": 18,
            "payment_fee_pct": 2,
            "return_rate_pct": 5,
            "service_area": "local",
            "business_address": "Str. Memorandumului 28, Cluj-Napoca",
            "business_kind": "programat",
            "max_travel_km": 4,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_cac"] == "110.00"
    assert body["break_even_roas"] == "2.28"
    assert body["target_radius_km"] == "4.00"
    assert body["next_question"] is None
    assert body["economics_confirmed_at"] is not None
    assert "ai cerut cel mult 4" in body["radius_reason"]


def test_the_agency_can_fill_in_the_costs_for_its_client(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post("/api/v1/clients", headers=auth_headers, json={"name": "Cabinet"})
    client_id = created.json()["id"]

    response = client.put(
        f"/api/v1/clients/{client_id}/economics",
        headers=auth_headers,
        json={"customer_profit": 900, "close_rate_pct": 25, "service_area": "national"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["max_cpl"] == "225.00"
    assert client.get(f"/api/v1/clients/{client_id}/economics", headers=auth_headers).json()[
        "summary"
    ].startswith("Un client nou îți aduce 900 lei profit")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.250,50 lei", "1250.50"), ("1,250.50", "1250.50"), ("2,5", "2.5"), ("1.250", "1250")],
)
def test_romanian_numbers(text: str, expected: str) -> None:
    assert parse_number(plain(text)) == Decimal(expected)


def test_shares() -> None:
    assert parse_share(plain("3 din 10"), out_of=10) == Decimal("30.00")
    assert parse_share(plain("30%"), out_of=10) == Decimal("30")
    assert parse_share(plain("nimic"), out_of=100) == Decimal("0")
