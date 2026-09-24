"""Fluxul OAuth Google: URL-ul de consimtamant si schimbul codului pe refresh token.

Fara retea: ``httpx.MockTransport``. Se verifica ce ar strica tacut conectarea:
un refresh token care nu vine (fara ``access_type=offline`` + ``prompt=consent``
Google il da doar la primul consimtamant) si un ``redirect_uri`` diferit intre
cei doi pasi (Google refuza atunci codul).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.search_data.google_oauth import (
    ANALYTICS_SCOPE,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    SEARCH_CONSOLE_SCOPE,
    build_consent_url,
    exchange_authorization_code,
)

_REDIRECT = "http://localhost:8000/api/v1/integrations/ga4/callback"


def test_url_de_consimtamant_cere_acces_offline_si_consimtamant_explicit() -> None:
    url = build_consent_url(
        client_id="client-123",
        redirect_uri=_REDIRECT,
        scopes=(ANALYTICS_SCOPE,),
        state="stare-semnata",
    )
    parts = urlsplit(url)
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}

    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == OAUTH_AUTHORIZE_URL
    assert params == {
        "client_id": "client-123",
        "redirect_uri": _REDIRECT,
        "response_type": "code",
        "scope": ANALYTICS_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": "stare-semnata",
    }


def test_mai_multe_scope_uri_se_trimit_separate_prin_spatiu() -> None:
    url = build_consent_url(
        client_id="c",
        redirect_uri=_REDIRECT,
        scopes=(SEARCH_CONSOLE_SCOPE, ANALYTICS_SCOPE),
        state="s",
    )
    scope = parse_qs(urlsplit(url).query)["scope"][0]
    assert scope.split(" ") == [SEARCH_CONSOLE_SCOPE, ANALYTICS_SCOPE]


def test_codul_se_schimba_pe_refresh_token_cu_acelasi_redirect_uri() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == OAUTH_TOKEN_URL
        seen.append({key: values[0] for key, values in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "refresh-xyz"})

    token = exchange_authorization_code(
        client_id="client-123",
        client_secret="secret",
        code="cod-de-la-google",
        redirect_uri=_REDIRECT,
        transport=httpx.MockTransport(handler),
    )

    assert token == "refresh-xyz"
    assert seen == [
        {
            "client_id": "client-123",
            "client_secret": "secret",
            "code": "cod-de-la-google",
            "redirect_uri": _REDIRECT,
            "grant_type": "authorization_code",
        }
    ]


def test_un_cod_refuzat_e_o_problema_de_configurare_nu_un_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(SetupRequiredError, match="invalid_grant"):
        exchange_authorization_code(
            client_id="c",
            client_secret="s",
            code="expirat",
            redirect_uri=_REDIRECT,
            transport=httpx.MockTransport(handler),
        )


def test_fara_refresh_token_in_raspuns_conectarea_nu_se_poate_face() -> None:
    """Fara refresh token, conexiunea ar muri la prima expirare a access token-ului."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "doar-access"})

    with pytest.raises(ProviderError, match="refresh_token"):
        exchange_authorization_code(
            client_id="c",
            client_secret="s",
            code="cod",
            redirect_uri=_REDIRECT,
            transport=httpx.MockTransport(handler),
        )
