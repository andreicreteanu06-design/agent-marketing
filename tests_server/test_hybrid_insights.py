"""Endpoint-urile motorului hibrid PPC+SEO si job-ul de sincronizare a pozitiilor.

Testele lovesc contractul HTTP si comportamentul job-ului (oprire la blocare,
ce se salveaza) - logica pura a analizelor are testele ei in
``tests/test_search_data.py`` si nu se re-testeaza aici.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.search_data.serp_tracker import OpenSerpProvider
from ppc_agent_server.jobs import serp_sync
from ppc_agent_server.models import (
    ClientAccount,
    SearchTermConversion,
    SerpPosition,
    SerpSource,
    Tenant,
    TrackedKeyword,
)

_HYBRID = "/api/v1/hybrid"


def _signup_and_login(client: TestClient) -> tuple[str, int]:
    """Creeaza un client si intoarce (token, client_account_id)."""
    response = client.post(
        "/api/v1/signup",
        json={
            "name": "Client Hibrid SRL",
            "email": "hibrid@exemplu.ro",
            "password": "parola-super-sigura",
        },
    )
    assert response.status_code == 201
    token = str(response.json()["access_token"])
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    return token, int(me.json()["account"]["id"])


@pytest.fixture
def hybrid_client(
    client: TestClient, agency_settings: Tenant, session: Session
) -> tuple[TestClient, dict[str, str], int]:
    token, account_id = _signup_and_login(client)
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.target_domain = "exemplu.ro"
    session.add(account)
    session.commit()
    return client, {"Authorization": f"Bearer {token}"}, account_id


def _add_paid_term(
    session: Session,
    account_id: int,
    term: str,
    *,
    cost: str,
    conversions: float,
    days_ago: int = 1,
) -> None:
    session.add(
        SearchTermConversion(
            client_account_id=account_id,
            day=datetime.now(tz=UTC) - timedelta(days=days_ago),
            search_term=term,
            clicks=10,
            cost=Decimal(cost),
            conversions=conversions,
            conversions_value=Decimal("1000"),
        )
    )
    session.commit()


def _add_position(
    session: Session, account_id: int, keyword: str, rank: float | None, *, days_ago: int = 0
) -> None:
    session.add(
        SerpPosition(
            client_account_id=account_id,
            checked_on=datetime.now(tz=UTC) - timedelta(days=days_ago),
            keyword=keyword,
            domain="exemplu.ro",
            source=SerpSource.OPENSERP,
            rank=rank,
        )
    )
    session.commit()


# --- endpoint-uri -----------------------------------------------------------


def test_endpointurile_cer_autentificare(client: TestClient) -> None:
    assert client.get(f"{_HYBRID}/keywords").status_code == 401
    assert client.get(f"{_HYBRID}/insights/cannibalization").status_code == 401


def test_adaugarea_unui_cuvant_il_intoarce(
    hybrid_client: tuple[TestClient, dict[str, str], int],
) -> None:
    client, headers, _ = hybrid_client
    response = client.post(
        f"{_HYBRID}/keywords",
        json={"keyword": "pantofi piele", "intent": "transactional"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["keyword"] == "pantofi piele"
    assert body["intent"] == "transactional"
    assert body["is_active"] is True


def test_readaugarea_reactiveaza_in_loc_sa_duplice(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    """Un duplicat ar rupe istoricul cuvantului in doua siruri identice la vedere."""
    client, headers, account_id = hybrid_client
    payload = {"keyword": "pantofi piele"}
    first = client.post(f"{_HYBRID}/keywords", json=payload, headers=headers).json()
    second = client.post(f"{_HYBRID}/keywords", json=payload, headers=headers).json()
    assert first["id"] == second["id"]
    rows = session.exec(
        select(TrackedKeyword).where(TrackedKeyword.client_account_id == account_id)
    ).all()
    assert len(rows) == 1


def test_listarea_imbina_pozitia_cu_datele_de_plata(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hybrid_client
    client.post(f"{_HYBRID}/keywords", json={"keyword": "pantofi piele"}, headers=headers)
    _add_position(session, account_id, "Pantofi Piele", 2.0)
    _add_paid_term(session, account_id, "pantofi piele", cost="450.00", conversions=6)

    (row,) = client.get(f"{_HYBRID}/keywords", headers=headers).json()
    assert row["latest_rank"] == 2.0
    assert row["latest_rank_source"] == "openserp"
    assert row["paid_cost"] == "450.00"
    # Comparatie numerica, nu pe text: scala zecimala a impartirii nu e
    # parte din contract, valoarea e.
    assert Decimal(row["paid_cpa"]) == Decimal("75")


def test_un_cuvant_fara_date_ramane_cu_campuri_nule(
    hybrid_client: tuple[TestClient, dict[str, str], int],
) -> None:
    """Null inseamna "nu s-a masurat"; un zero ar sterge distinctia."""
    client, headers, _ = hybrid_client
    client.post(f"{_HYBRID}/keywords", json={"keyword": "cuvant nou"}, headers=headers)
    (row,) = client.get(f"{_HYBRID}/keywords", headers=headers).json()
    assert row["latest_rank"] is None
    assert row["paid_cost"] is None


def test_canibalizarea_raporteaza_termenii_detinuti_organic(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hybrid_client
    _add_paid_term(session, account_id, "pantofi piele", cost="450.00", conversions=6)
    _add_position(session, account_id, "pantofi piele", 2.0)
    _add_paid_term(session, account_id, "cizme dama", cost="200.00", conversions=4)
    _add_position(session, account_id, "cizme dama", 24.0)

    body = client.get(f"{_HYBRID}/insights/cannibalization", headers=headers).json()
    assert [item["term"] for item in body["items"]] == ["pantofi piele"]
    assert body["total_potential_saving"] == "450.00"
    assert body["top_position_threshold"] == 3.0


def test_oportunitatile_raporteaza_golurile_care_convertesc(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hybrid_client
    _add_paid_term(session, account_id, "cizme dama", cost="200.00", conversions=4)
    _add_position(session, account_id, "cizme dama", 24.0)
    _add_paid_term(session, account_id, "fara conversii", cost="300.00", conversions=0)

    body = client.get(f"{_HYBRID}/insights/opportunities", headers=headers).json()
    assert [item["term"] for item in body["items"]] == ["cizme dama"]
    assert body["items"][0]["organic_position"] == 24.0


def test_fereastra_de_analiza_exclude_datele_vechi(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hybrid_client
    _add_paid_term(session, account_id, "vechi", cost="500.00", conversions=9, days_ago=60)
    _add_position(session, account_id, "vechi", 1.0)

    body = client.get(
        f"{_HYBRID}/insights/cannibalization", headers=headers, params={"days": 30}
    ).json()
    assert body["items"] == []


def test_un_client_nu_vede_cuvintele_altuia(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    client, headers, account_id = hybrid_client
    session.add(TrackedKeyword(client_account_id=account_id + 999, keyword="al altuia"))
    session.commit()
    assert client.get(f"{_HYBRID}/keywords", headers=headers).json() == []


# --- job-ul de sincronizare -------------------------------------------------


def _provider(handler: object) -> OpenSerpProvider:
    return OpenSerpProvider(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _seed_keywords(session: Session, account_id: int, *words: str) -> None:
    for word in words:
        session.add(TrackedKeyword(client_account_id=account_id, keyword=word))
    session.commit()


def test_jobul_salveaza_pozitiile_gasite(
    hybrid_client: tuple[TestClient, dict[str, str], int],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, account_id = hybrid_client
    _seed_keywords(session, account_id, "unu", "doi")
    monkeypatch.setattr(
        serp_sync,
        "_build_provider",
        lambda settings: _provider(
            lambda request: httpx.Response(
                200, json=[{"type": "organic", "url": "https://exemplu.ro/p"}]
            )
        ),
    )

    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)
    assert result["checked"] == 2
    assert result["saved"] == 2
    rows = session.exec(
        select(SerpPosition).where(SerpPosition.client_account_id == account_id)
    ).all()
    assert [row.rank for row in rows] == [1.0, 1.0]
    assert all(row.source is SerpSource.OPENSERP for row in rows)


def test_jobul_se_opreste_la_prima_blocare(
    hybrid_client: tuple[TestClient, dict[str, str], int],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fiecare interogare in plus dupa un CAPTCHA adanceste blocarea."""
    _, _, account_id = hybrid_client
    _seed_keywords(session, account_id, "unu", "doi", "trei")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.params["text"]))
        return httpx.Response(200, text="Our systems detected unusual traffic")

    monkeypatch.setattr(serp_sync, "_build_provider", lambda settings: _provider(handler))
    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)

    assert result["halted"] == "blocked"
    assert len(calls) == 1  # nu s-a continuat cu celelalte doua
    assert result["saved"] == 0


def test_o_eroare_punctuala_nu_opreste_restul(
    hybrid_client: tuple[TestClient, dict[str, str], int],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spre deosebire de blocare, o eroare izolata nu se agraveaza prin continuare."""
    _, _, account_id = hybrid_client
    _seed_keywords(session, account_id, "unu", "doi")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["text"] == "unu":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=[{"type": "organic", "url": "https://exemplu.ro/"}])

    monkeypatch.setattr(serp_sync, "_build_provider", lambda settings: _provider(handler))
    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)
    assert result["checked"] == 2
    assert result["saved"] == 1
    assert result["halted"] == ""


def test_domeniul_lipsa_sare_peste_client(
    hybrid_client: tuple[TestClient, dict[str, str], int], session: Session
) -> None:
    _, _, account_id = hybrid_client
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.target_domain = ""
    session.add(account)
    session.commit()

    result = serp_sync.run_serp_sync_job(client_account_id=account_id, sleep_between=False)
    assert "skipped" in result
