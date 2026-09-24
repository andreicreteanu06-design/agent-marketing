"""Schimbul refresh token -> access token pentru API-urile Google.

Extras aici fiindca il folosesc DOUA clientele noi (Search Console si Keyword
Planner) si ar fi fost copiat de doua ori. ``providers/live/google_ads.py`` are
propria copie, mai veche, si ramane neatins deliberat: e acoperit de teste care
trec, iar refactorizarea lui n-ar schimba niciun comportament - doar ar risca
sa strice ceva ce merge. Daca mai apare un al treilea consumator, atunci merita
mutat si el aici.

Nota despre SCOPE-uri, care e capcana reala: un refresh token Google e legat de
scope-urile pentru care clientul a dat consimtamant. Token-ul de Google Ads
(scope ``adwords``) NU merge pentru Search Console (scope ``webmasters``) - de
aceea ``ClientAccount`` are doua campuri separate, nu unul refolosit.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlencode

import httpx

from ppc_agent.errors import ProviderError, SetupRequiredError

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

#: Scope-ul cerut de Search Console API (doar citire - nu modificam nimic).
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
#: Scope-ul cerut de Google Analytics (Data API si Admin API) - doar citire.
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
#: Scope-ul cerut de Google Ads API (inclusiv Keyword Planner).
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"


def build_consent_url(
    *, client_id: str, redirect_uri: str, scopes: Sequence[str], state: str
) -> str:
    """URL-ul ecranului de consimtamant Google (fluxul Authorization Code).

    ``access_type=offline`` + ``prompt=consent``: fara ele, Google da refresh
    token-ul doar la PRIMUL consimtamant al unui cont. O reconectare (alt cont
    Google, token revocat) ar primi doar un access token de o ora, iar
    integrarea ar muri tacut la expirarea lui.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Refresh token-ul obtinut din codul de autorizare - pasul 2 al fluxului OAuth.

    ``redirect_uri`` trebuie sa fie EXACT cel din :func:`build_consent_url`;
    altfel Google refuza codul (``redirect_uri_mismatch``).

    Raises:
        SetupRequiredError: Google refuza codul (expirat, deja folosit, alt
            client OAuth) sau nu raspunde - utilizatorul reia conectarea.
        ProviderError: raspunsul nu contine ``refresh_token``.
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.post(OAUTH_TOKEN_URL, data=payload)
    except httpx.HTTPError as exc:
        raise SetupRequiredError(f"Nu se poate contacta {OAUTH_TOKEN_URL}: {exc}") from exc

    if response.status_code >= 400:
        raise SetupRequiredError(
            f"Google OAuth2 a refuzat codul de autorizare ({response.status_code}): "
            f"{response.text[:200]}"
        )
    try:
        refresh_token = response.json().get("refresh_token")
    except ValueError as exc:
        raise ProviderError(f"raspuns OAuth2 Google neasteptat: {exc}") from exc
    if not refresh_token:
        raise ProviderError(
            "Google nu a trimis refresh_token - fara el conexiunea ar expira intr-o ora."
        )
    return str(refresh_token)


def revoke_token(
    token: str, *, timeout: float = 15.0, transport: httpx.BaseTransport | None = None
) -> bool:
    """Revoca un token la Google - la deconectare, ca accesul sa inceteze si acolo.

    Best effort: intoarce ``False`` la orice esec, fara exceptie. Deconectarea
    sterge oricum token-ul din baza de date; un token deja revocat de client
    din contul Google e cazul obisnuit, nu o eroare.
    """
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.post(OAUTH_REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        return False
    return response.status_code < 400


def exchange_refresh_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
    missing_message: str,
) -> str:
    """Intoarce un access token OAuth2 valabil, pornind de la ``refresh_token``.

    Args:
        missing_message: ce ii spunem utilizatorului cand lipsesc credentialele.
            Il primeste apelantul, ca mesajul sa numeasca variabilele LUI
            (Search Console si Google Ads au setari diferite).

    Raises:
        SetupRequiredError: credentiale lipsa, Google inaccesibil, sau refresh
            token refuzat (revocat/expirat/scope gresit) - toate sunt probleme
            de configurare, pe care le rezolva utilizatorul, nu un retry.
        ProviderError: Google a raspuns 200, dar fara ``access_token``.
    """
    if not (client_id and client_secret and refresh_token):
        raise SetupRequiredError(missing_message)

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.post(OAUTH_TOKEN_URL, data=payload)
    except httpx.ConnectError as exc:
        raise SetupRequiredError(
            f"Nu se poate contacta {OAUTH_TOKEN_URL} pentru refresh OAuth2."
        ) from exc
    except httpx.TimeoutException as exc:
        raise SetupRequiredError(f"OAuth2 Google nu a raspuns in {timeout:.0f}s.") from exc

    if response.status_code >= 400:
        raise SetupRequiredError(
            f"Google OAuth2 a refuzat refresh_token-ul ({response.status_code}): "
            f"{response.text[:200]}. Verifica daca a fost generat cu scope-ul potrivit "
            "si daca nu a fost revocat."
        )
    try:
        return str(response.json()["access_token"])
    except (KeyError, ValueError) as exc:
        raise ProviderError(f"raspuns OAuth2 Google neasteptat: {exc}") from exc
