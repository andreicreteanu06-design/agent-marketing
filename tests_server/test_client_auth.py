"""Teste pentru autentificarea self-service a clientilor (/signup, /login,
/me, /me/credentials) - distincta de auth-ul de agentie (cheie API)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import ppc_agent_server.routers.client_auth as client_auth_module
import ppc_agent_server.security as security_module
from ppc_agent_server.models import ClientAccount, ClientUser, Tenant
from ppc_agent_server.settings import ServerSettings

# Cheie fixa, folosita doar cand testul are nevoie ca JWT_SECRET_KEY sa fie
# valid ca sa poata izola un ALT cec (ex. AGENCY_TENANT_ID lipsa). Constructia
# directa ServerSettings(...) (nu monkeypatch pe variabile de mediu) ocoleste
# complet .env-ul real al masinii care ruleaza testul - un .env de dezvoltare
# cu JWT_SECRET_KEY/SECRETS_KEY/AGENCY_TENANT_ID deja completate (cazul curent
# al acestui proiect, dupa verificarea live) ar altfel "scurge" in aceste
# teste si le-ar face sa treaca din intamplare, din alt motiv - gasit real.
_VALID_JWT_KEY = "test-jwt-secret-at-least-32-bytes-long"


def _signup(client: TestClient, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Client Nou SRL",
        "email": "client@exemplu.ro",
        "password": "parola-super-sigura",
    }
    payload.update(overrides)
    response = client.post("/api/v1/signup", json=payload)
    assert response.status_code == 201
    return dict(response.json())


def _get_account(session: Session, *, name: str = "Client Nou SRL") -> ClientAccount:
    return session.exec(select(ClientAccount).where(ClientAccount.name == name)).one()


def test_signup_requires_agency_tenant_id_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fara AGENCY_TENANT_ID, /signup e 503. JWT_SECRET_KEY valid explicit, ca
    testul sa izoleze exact acest cec (al doilea, dupa cel de JWT)."""
    fake = ServerSettings(jwt_secret_key=_VALID_JWT_KEY, agency_tenant_id=None)
    monkeypatch.setattr(client_auth_module, "get_server_settings", lambda: fake)

    response = client.post(
        "/api/v1/signup",
        json={"name": "X", "email": "x@exemplu.ro", "password": "parola12345"},
    )
    assert response.status_code == 503


def test_signup_creates_account_and_returns_token(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    body = _signup(client)
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    account = _get_account(session)
    assert account.tenant_id == agency_settings.id

    user = session.exec(select(ClientUser).where(ClientUser.email == "client@exemplu.ro")).one()
    assert user.client_account_id == account.id
    # Parola nu ajunge niciodata in clar in DB.
    assert user.password_hash != "parola-super-sigura"
    assert user.password_hash.startswith("$argon2")


def test_signup_rejects_duplicate_email(client: TestClient, agency_settings: Tenant) -> None:
    _signup(client)
    response = client.post(
        "/api/v1/signup",
        json={"name": "Alt Client", "email": "client@exemplu.ro", "password": "altaparola123"},
    )
    assert response.status_code == 409


def test_signup_saves_the_email_in_lowercase_and_login_ignores_case(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    _signup(client, email="  Client@Exemplu.RO ")
    assert session.exec(select(ClientUser)).one().email == "client@exemplu.ro"

    duplicate = client.post(
        "/api/v1/signup",
        json={"name": "Alt Client", "email": "CLIENT@exemplu.ro", "password": "altaparola123"},
    )
    assert duplicate.status_code == 409

    login = client.post(
        "/api/v1/login", json={"email": "CLIENT@EXEMPLU.ro", "password": "parola-super-sigura"}
    )
    assert login.status_code == 200


def test_an_account_saved_before_lowercase_emails_still_logs_in(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    """Conturile vechi au emailul cum l-a scris omul; cautarea ignora literele mari."""
    account = ClientAccount(tenant_id=agency_settings.id, name="Vechi SRL")
    session.add(account)
    session.commit()
    session.refresh(account)
    session.add(
        ClientUser(
            client_account_id=account.id,
            email="Vechi@Exemplu.ro",
            password_hash=security_module.hash_password("parola-veche-123"),
        )
    )
    session.commit()

    login = client.post(
        "/api/v1/login", json={"email": "vechi@exemplu.ro", "password": "parola-veche-123"}
    )
    assert login.status_code == 200
    taken = client.post(
        "/api/v1/signup",
        json={"name": "Altul", "email": "VECHI@exemplu.ro", "password": "parola-noua-123"},
    )
    assert taken.status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "fara-arond"},
        {"email": "a@b"},
        {"email": "x" * 250 + "@exemplu.ro"},
        {"name": ""},
        {"name": "N" * 201},
        {"password": "p" * 257},
    ],
)
def test_signup_rejects_malformed_or_oversized_fields(
    client: TestClient, agency_settings: Tenant, session: Session, overrides: dict[str, str]
) -> None:
    payload = {"name": "Client", "email": "client@exemplu.ro", "password": "parola-super-sigura"}
    payload.update(overrides)
    assert client.post("/api/v1/signup", json=payload).status_code == 422
    assert session.exec(select(ClientUser)).first() is None


def test_login_succeeds_with_correct_password(
    client: TestClient, agency_settings: Tenant
) -> None:
    _signup(client)
    response = client.post(
        "/api/v1/login", json={"email": "client@exemplu.ro", "password": "parola-super-sigura"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_rejects_wrong_password(client: TestClient, agency_settings: Tenant) -> None:
    _signup(client)
    response = client.post(
        "/api/v1/login", json={"email": "client@exemplu.ro", "password": "gresita"}
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email_with_same_message_as_wrong_password(
    client: TestClient, agency_settings: Tenant
) -> None:
    """Acelasi mesaj pentru "nu exista" si "parola gresita" - nu se poate
    distinge daca un email e inregistrat (previne enumerarea de conturi)."""
    _signup(client)
    wrong_password = client.post(
        "/api/v1/login", json={"email": "client@exemplu.ro", "password": "gresita"}
    )
    unknown_email = client.post(
        "/api/v1/login", json={"email": "nu-exist@exemplu.ro", "password": "orice"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401


def test_me_rejects_garbage_token(client: TestClient, agency_settings: Tenant) -> None:
    response = client.get(
        "/api/v1/me", headers={"Authorization": "Bearer nu-e-un-token-jwt-valid"}
    )
    assert response.status_code == 401


def test_me_without_jwt_secret_key_configured_returns_503_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JWT_SECRET_KEY neconfigurat e o eroare de operare server (503), nu un
    crash brut (500) - gasit real, prin acest test, inainte de fix. decode_client_token
    (security.py) e ce citeste JWT_SECRET_KEY pe calea /me, nu client_auth.py direct."""
    fake = ServerSettings(jwt_secret_key="")
    monkeypatch.setattr(security_module, "get_server_settings", lambda: fake)

    response = client.get("/api/v1/me", headers={"Authorization": "Bearer orice"})
    assert response.status_code == 503


def test_signup_without_jwt_secret_key_configured_returns_503_before_writing_rows(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JWT_SECRET_KEY se verifica INAINTE de a crea ClientAccount/ClientUser -
    altfel ar ramane un cont orfan, fara nicio cale de a obtine un token."""
    fake = ServerSettings(jwt_secret_key="", agency_tenant_id=1)
    monkeypatch.setattr(client_auth_module, "get_server_settings", lambda: fake)

    response = client.post(
        "/api/v1/signup",
        json={"name": "X", "email": "orfan@exemplu.ro", "password": "parola12345"},
    )
    assert response.status_code == 503
    assert (
        session.exec(select(ClientAccount).where(ClientAccount.name == "X")).first() is None
    )


def test_me_returns_own_identity_and_account(
    client: TestClient, agency_settings: Tenant
) -> None:
    token = _signup(client)["access_token"]
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "client@exemplu.ro"
    assert body["account"]["name"] == "Client Nou SRL"
    # Niciun cont de reclame conectat inca - toate patru false, nu doar absente.
    assert body["google_ads_connected"] is False
    assert body["meta_connected"] is False
    assert body["tiktok_connected"] is False
    assert body["chatgpt_connected"] is False


def test_me_connection_flags_follow_credentials_update(
    client: TestClient, agency_settings: Tenant
) -> None:
    """Dupa ce clientul conecteaza DOAR Google, ``/me`` reflecta exact asta -
    Google trece pe true, Meta/TikTok/ChatGPT raman false (interfata foloseste
    aceste flag-uri pentru insigna "Conectat", nu valoarea in clar)."""
    token = _signup(client)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.patch(
        "/api/v1/me/credentials",
        headers=headers,
        json={"google_ads_refresh_token": "1//refresh-token"},
    )

    body = client.get("/api/v1/me", headers=headers).json()
    assert body["google_ads_connected"] is True
    assert body["meta_connected"] is False
    assert body["tiktok_connected"] is False
    assert body["chatgpt_connected"] is False


def test_chatgpt_ads_api_key_updates_connection_flag(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    """La fel ca Google/Meta/TikTok - chatgpt_ads_api_key se cripteaza, nu se
    ecoueaza, si actualizeaza doar flag-ul chatgpt_connected."""
    token = _signup(client)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/me/credentials",
        headers=headers,
        json={"chatgpt_ads_api_key": "sk-super-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"updated_fields": ["chatgpt_ads_api_key"]}
    assert "sk-super-secret" not in response.text

    body = client.get("/api/v1/me", headers=headers).json()
    assert body["chatgpt_connected"] is True
    assert body["google_ads_connected"] is False

    account = _get_account(session)
    assert account.chatgpt_ads_api_key_enc != ""
    assert "sk-super-secret" not in account.chatgpt_ads_api_key_enc


def test_credentials_update_encrypts_and_never_echoes_raw_value(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    token = _signup(client)["access_token"]
    response = client.patch(
        "/api/v1/me/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"google_ads_refresh_token": "1//super-secret-refresh-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"updated_fields": ["google_ads_refresh_token"]}
    # Raspunsul nu contine niciodata valoarea, criptata sau nu.
    assert "1//super-secret-refresh-token" not in response.text

    account = _get_account(session)
    assert account.google_ads_refresh_token_enc != ""
    assert account.google_ads_refresh_token_enc != "1//super-secret-refresh-token"
    assert "1//super-secret-refresh-token" not in account.google_ads_refresh_token_enc


def test_credentials_update_requires_authentication(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/me/credentials", json={"meta_access_token": "orice"}
    )
    assert response.status_code == 401


def test_credentials_update_only_touches_sent_fields(
    client: TestClient, agency_settings: Tenant, session: Session
) -> None:
    token = _signup(client)["access_token"]
    client.patch(
        "/api/v1/me/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"google_ads_refresh_token": "token-google"},
    )
    response = client.patch(
        "/api/v1/me/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"meta_access_token": "token-meta"},
    )
    assert response.json() == {"updated_fields": ["meta_access_token"]}

    account = _get_account(session)
    assert account.google_ads_refresh_token_enc != ""  # neatins de al doilea PATCH
    assert account.meta_access_token_enc != ""


def test_two_clients_have_fully_isolated_tokens_and_credentials(
    client: TestClient, agency_settings: Tenant
) -> None:
    """Token-ul unui client nu poate niciodata sa citeasca/scrie contul altuia
    - /me si /me/credentials rezolva mereu din token, niciodata dintr-un ID
    trimis de apelant, deci nu exista nicio cale de a tinti alt cont."""
    token_a = _signup(client, name="Client A", email="a@exemplu.ro")["access_token"]
    token_b = _signup(client, name="Client B", email="b@exemplu.ro")["access_token"]

    client.patch(
        "/api/v1/me/credentials",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"google_ads_refresh_token": "secret-A"},
    )

    me_a = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    me_b = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert me_a["account"]["name"] == "Client A"
    assert me_b["account"]["name"] == "Client B"
    assert me_a["account"]["id"] != me_b["account"]["id"]
