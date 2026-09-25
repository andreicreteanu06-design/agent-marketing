"""Integrarile Google ale clientului: Search Console si Google Analytics 4.

Fluxul OAuth are doi pasi, iar testele ii acopera pe amandoi fara retea:
URL-ul de consimtamant (cu o stare semnata) si callback-ul pe care Google il
apeleaza cu codul. Apelurile catre Google trec printr-un ``httpx.MockTransport``
injectat ca dependinta, la fel ca motorul fals de audit din agentul SEO.

Ce ar fi grav si e verificat explicit: o stare falsificata sau emisa pentru
alta integrare nu salveaza nimic, iar starea OAuth nu poate fi folosita ca
token de sesiune (e semnata cu o cheie derivata, nu cu cea a sesiunilor).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppc_agent.search_data.google_oauth import (
    ANALYTICS_SCOPE,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    SEARCH_CONSOLE_SCOPE,
)
from ppc_agent_server.models import ClientAccount, Tenant
from ppc_agent_server.routers import integrations
from ppc_agent_server.security import create_oauth_state, decrypt_secret, encrypt_secret

_SITE_INTEGRATIONS_PAGE = "http://localhost:3000/cont/seo-geo/integrari"

Handler = Callable[[httpx.Request], httpx.Response]


def _google(handler: Handler) -> Callable[[], httpx.BaseTransport]:
    return lambda: httpx.MockTransport(handler)


def _token_endpoint(request: httpx.Request) -> httpx.Response:
    """Google: codul de autorizare -> refresh token, refresh token -> access token."""
    form = parse_qs(request.content.decode())
    if form.get("grant_type") == ["authorization_code"]:
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "refresh-nou"})
    return httpx.Response(200, json={"access_token": "access-proaspat"})


@pytest.fixture
def app_client(
    client: TestClient, agency_settings: Tenant
) -> Iterator[tuple[TestClient, FastAPI]]:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[integrations.get_google_oauth_client] = lambda: (
        integrations.GoogleOAuthClient(client_id="client-123", client_secret="secret")
    )
    app.dependency_overrides[integrations.get_google_transport] = _google(_token_endpoint)
    yield client, app
    app.dependency_overrides.clear()


@pytest.fixture
def signed_in(
    app_client: tuple[TestClient, FastAPI],
) -> tuple[TestClient, FastAPI, dict[str, str], int]:
    client, app = app_client
    response = client.post(
        "/api/v1/signup",
        json={"name": "Arting Auto", "email": "client@exemplu.ro", "password": "parola-sigura-123"},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    account_id = int(client.get("/api/v1/me", headers=headers).json()["account"]["id"])
    return client, app, headers, account_id


def _state_from_auth_url(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.get(f"/api/v1/integrations/{name}/auth-url", headers=headers)
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(response.json()["auth_url"]).query)["state"][0]


def _callback(client: TestClient, name: str, **params: str) -> httpx.Response:
    return client.get(
        f"/api/v1/integrations/{name}/callback", params=params, follow_redirects=False
    )


def _redirect_params(response: httpx.Response) -> dict[str, str]:
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == _SITE_INTEGRATIONS_PAGE
    return {key: values[0] for key, values in parse_qs(location.query).items()}


# --- starea si URL-ul de autorizare --------------------------------------------


def test_fara_conectare_ambele_integrari_apar_neconectate(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    response = client.get("/api/v1/integrations", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "oauth_configured": True,
        "gsc": {"connected": False, "property_id": ""},
        "ga4": {"connected": False, "property_id": ""},
    }


def test_fara_client_oauth_pe_server_mesajul_spune_exact_ce_lipseste(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, app, headers, _ = signed_in
    app.dependency_overrides[integrations.get_google_oauth_client] = lambda: None

    assert client.get("/api/v1/integrations", headers=headers).json()["oauth_configured"] is False
    response = client.get("/api/v1/integrations/ga4/auth-url", headers=headers)
    assert response.status_code == 503
    assert "PPC_GOOGLE_OAUTH_CLIENT_ID" in response.json()["detail"]


@pytest.mark.parametrize(
    ("name", "scope"), [("ga4", ANALYTICS_SCOPE), ("gsc", SEARCH_CONSOLE_SCOPE)]
)
def test_url_de_autorizare_duce_la_google_si_inapoi_pe_callback(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], name: str, scope: str
) -> None:
    client, _, headers, _ = signed_in
    response = client.get(f"/api/v1/integrations/{name}/auth-url", headers=headers)

    url = urlsplit(response.json()["auth_url"])
    params = {key: values[0] for key, values in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == OAUTH_AUTHORIZE_URL
    assert params["client_id"] == "client-123"
    assert params["redirect_uri"] == f"http://localhost:8000/api/v1/integrations/{name}/callback"
    assert params["scope"] == scope
    assert params["state"]


# --- callback-ul ------------------------------------------------------------


def test_callback_salveaza_tokenul_criptat_si_intoarce_clientul_pe_site(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    state = _state_from_auth_url(client, headers, "ga4")

    params = _redirect_params(_callback(client, "ga4", code="cod-google", state=state))

    assert params == {"conectat": "ga4"}
    account = session.get(ClientAccount, account_id)
    assert account is not None
    session.refresh(account)
    assert decrypt_secret(account.ga4_refresh_token_enc) == "refresh-nou"
    status = client.get("/api/v1/integrations", headers=headers).json()
    assert status["ga4"]["connected"] is True
    assert status["gsc"]["connected"] is False


def test_o_stare_falsificata_nu_salveaza_nimic(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, _, account_id = signed_in
    params = _redirect_params(_callback(client, "ga4", code="cod", state="stare-inventata"))

    assert params == {"eroare": "sesiune_expirata", "integrare": "ga4"}
    account = session.get(ClientAccount, account_id)
    assert account is not None and account.ga4_refresh_token_enc == ""


def test_starea_emisa_pentru_ga4_nu_merge_pe_callbackul_de_search_console(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    state = _state_from_auth_url(client, headers, "ga4")

    params = _redirect_params(_callback(client, "gsc", code="cod", state=state))

    assert params["eroare"] == "sesiune_expirata"
    account = session.get(ClientAccount, account_id)
    assert account is not None and account.gsc_refresh_token_enc == ""


def test_refuzul_de_pe_ecranul_google_se_intoarce_ca_mesaj_nu_ca_eroare_de_server(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    state = _state_from_auth_url(client, headers, "gsc")

    params = _redirect_params(_callback(client, "gsc", error="access_denied", state=state))
    assert params == {"eroare": "acces_refuzat", "integrare": "gsc"}


def test_un_cod_refuzat_de_google_nu_salveaza_nimic(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    app.dependency_overrides[integrations.get_google_transport] = _google(
        lambda request: httpx.Response(400, json={"error": "invalid_grant"})
    )
    state = _state_from_auth_url(client, headers, "ga4")

    params = _redirect_params(_callback(client, "ga4", code="expirat", state=state))

    assert params == {"eroare": "schimb_esuat", "integrare": "ga4"}
    account = session.get(ClientAccount, account_id)
    assert account is not None and account.ga4_refresh_token_enc == ""


def test_starea_unui_cont_sters_nu_creeaza_nimic(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, _, _ = signed_in
    state = create_oauth_state(999_999, "ga4")

    params = _redirect_params(_callback(client, "ga4", code="cod", state=state))
    assert params == {"eroare": "cont_inexistent", "integrare": "ga4"}


def test_starea_oauth_nu_poate_fi_folosita_ca_token_de_sesiune(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    """Starea apare in URL-ul de la Google - n-are voie sa deschida contul cuiva."""
    client, _, headers, _ = signed_in
    state = _state_from_auth_url(client, headers, "ga4")

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {state}"})
    assert response.status_code == 401


# --- proprietatile ----------------------------------------------------------


def _connect(session: Session, account_id: int, field: str) -> None:
    account = session.get(ClientAccount, account_id)
    assert account is not None
    setattr(account, field, encrypt_secret("refresh-existent"))
    session.add(account)
    session.commit()


def test_proprietatile_cer_intai_conectarea_contului_google(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    response = client.get("/api/v1/integrations/ga4/properties", headers=headers)
    assert response.status_code == 409


def test_proprietatile_ga4_vin_din_contul_google_al_clientului(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _connect(session, account_id, "ga4_refresh_token_enc")
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return _token_endpoint(request)
        seen_tokens.append(request.headers["authorization"])
        assert request.url.host == "analyticsadmin.googleapis.com"
        return httpx.Response(
            200,
            json={
                "accountSummaries": [
                    {
                        "displayName": "Arting Auto SRL",
                        "propertySummaries": [
                            {"property": "properties/123456789", "displayName": "artingauto.ro"}
                        ],
                    },
                    {"displayName": "Cont fara proprietati"},
                ]
            },
        )

    app.dependency_overrides[integrations.get_google_transport] = _google(handler)
    response = client.get("/api/v1/integrations/ga4/properties", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == [{"id": "123456789", "label": "artingauto.ro · Arting Auto SRL"}]
    assert seen_tokens == ["Bearer access-proaspat"]


def test_proprietatile_search_console_vin_din_contul_google_al_clientului(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _connect(session, account_id, "gsc_refresh_token_enc")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            return _token_endpoint(request)
        assert request.url.path == "/webmasters/v3/sites"
        return httpx.Response(
            200,
            json={
                "siteEntry": [
                    {"siteUrl": "sc-domain:artingauto.ro", "permissionLevel": "siteOwner"},
                    {"siteUrl": "https://www.artingauto.ro/", "permissionLevel": "siteFullUser"},
                    {"siteUrl": "https://alt-site.ro/", "permissionLevel": "siteUnverifiedUser"},
                ]
            },
        )

    app.dependency_overrides[integrations.get_google_transport] = _google(handler)
    response = client.get("/api/v1/integrations/gsc/properties", headers=headers)

    assert response.status_code == 200, response.text
    # Proprietatile neverificate nu dau date, deci nu apar in lista.
    assert response.json() == [
        {"id": "sc-domain:artingauto.ro", "label": "artingauto.ro (tot domeniul)"},
        {"id": "https://www.artingauto.ro/", "label": "https://www.artingauto.ro/"},
    ]


def test_un_token_revocat_cere_reconectare_nu_da_eroare_de_server(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, app, headers, account_id = signed_in
    _connect(session, account_id, "ga4_refresh_token_enc")
    app.dependency_overrides[integrations.get_google_transport] = _google(
        lambda request: httpx.Response(400, json={"error": "invalid_grant"})
    )

    response = client.get("/api/v1/integrations/ga4/properties", headers=headers)
    assert response.status_code == 409
    assert "reconect" in response.json()["detail"].lower()


def test_alegerea_proprietatii_se_salveaza_normalizata(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in

    ga4 = client.patch(
        "/api/v1/integrations/ga4", headers=headers, json={"property_id": "properties/123456789"}
    )
    gsc = client.patch(
        "/api/v1/integrations/gsc", headers=headers, json={"property_id": "sc-domain:artingauto.ro"}
    )

    assert ga4.status_code == 200 and ga4.json()["property_id"] == "123456789"
    assert gsc.status_code == 200 and gsc.json()["property_id"] == "sc-domain:artingauto.ro"
    status = client.get("/api/v1/integrations", headers=headers).json()
    assert status["ga4"]["property_id"] == "123456789"
    assert status["gsc"]["property_id"] == "sc-domain:artingauto.ro"


@pytest.mark.parametrize(
    ("name", "property_id"),
    [("ga4", "G-ABC123"), ("ga4", "12ab"), ("gsc", "artingauto.ro"), ("gsc", "ftp://x.ro/")],
)
def test_o_proprietate_in_forma_gresita_e_refuzata(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], name: str, property_id: str
) -> None:
    """``G-ABC123`` e ID-ul de masurare al fluxului, nu al proprietatii - greseala tipica."""
    client, _, headers, _ = signed_in
    response = client.patch(
        f"/api/v1/integrations/{name}", headers=headers, json={"property_id": property_id}
    )
    assert response.status_code == 422


def test_deconectarea_sterge_tokenul_si_proprietatea(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    client, _, headers, account_id = signed_in
    _connect(session, account_id, "ga4_refresh_token_enc")
    client.patch("/api/v1/integrations/ga4", headers=headers, json={"property_id": "123"})

    response = client.delete("/api/v1/integrations/ga4", headers=headers)

    assert response.status_code == 204
    assert client.get("/api/v1/integrations", headers=headers).json()["ga4"] == {
        "connected": False,
        "property_id": "",
    }


def test_deconectarea_revoca_tokenul_si_la_google(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], session: Session
) -> None:
    """Stergerea din baza de date nu opreste accesul - token-ul ramane valabil la Google."""
    client, app, headers, account_id = signed_in
    _connect(session, account_id, "gsc_refresh_token_enc")
    revoked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        revoked.append(f"{request.url.path}:{parse_qs(request.content.decode())['token'][0]}")
        return httpx.Response(200)

    app.dependency_overrides[integrations.get_google_transport] = _google(handler)
    assert client.delete("/api/v1/integrations/gsc", headers=headers).status_code == 204
    assert revoked == ["/revoke:refresh-existent"]


def test_integrarile_cer_autentificare(client: TestClient) -> None:
    assert client.get("/api/v1/integrations").status_code == 401
    assert client.get("/api/v1/integrations/ga4/auth-url").status_code == 401


def test_o_integrare_necunoscuta_e_refuzata(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    assert client.get("/api/v1/integrations/facebook/auth-url", headers=headers).status_code == 422


# --- setarile site-ului -----------------------------------------------------


def test_domeniul_si_brandul_se_salveaza_din_setari(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    response = client.patch(
        "/api/v1/me/site",
        headers=headers,
        json={"target_domain": " www.ArtingAuto.ro/contact ", "brand_name": " Arting Auto "},
    )

    assert response.status_code == 200, response.text
    account = client.get("/api/v1/me", headers=headers).json()["account"]
    assert account["target_domain"] == "https://www.artingauto.ro"
    assert account["brand_name"] == "Arting Auto"


def test_un_domeniu_invalid_e_refuzat_iar_unul_gol_sterge_valoarea(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int],
) -> None:
    client, _, headers, _ = signed_in
    invalid = client.patch("/api/v1/me/site", headers=headers, json={"target_domain": "nu e site"})
    assert invalid.status_code == 422

    client.patch("/api/v1/me/site", headers=headers, json={"target_domain": "artingauto.ro"})
    cleared = client.patch("/api/v1/me/site", headers=headers, json={"target_domain": ""})
    assert cleared.status_code == 200
    assert cleared.json()["target_domain"] == ""


@pytest.mark.parametrize(
    "internal",
    ["127.0.0.1", "10.0.0.5", "169.254.169.254", "100.64.0.1", "intern.localhost",
     "metadata.google.internal", "nas.local"],
)
def test_domeniul_nu_poate_fi_o_adresa_interna(
    signed_in: tuple[TestClient, FastAPI, dict[str, str], int], internal: str
) -> None:
    """Agentul crawleaza domeniul noaptea - o adresa interna ar fi o poarta SSRF."""
    client, _, headers, _ = signed_in
    response = client.patch("/api/v1/me/site", headers=headers, json={"target_domain": internal})
    assert response.status_code == 422
    assert "nu o adresă internă" in response.text
