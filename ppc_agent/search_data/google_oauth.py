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

import httpx

from ppc_agent.errors import ProviderError, SetupRequiredError

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

#: Scope-ul cerut de Search Console API (doar citire - nu modificam nimic).
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
#: Scope-ul cerut de Google Ads API (inclusiv Keyword Planner).
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"


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
