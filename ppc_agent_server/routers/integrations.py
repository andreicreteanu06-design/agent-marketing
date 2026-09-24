"""Integrarile Google ale clientului: Search Console si Google Analytics 4.

Fluxul OAuth (Authorization Code), in trei pasi:

1. Site-ul cere ``GET /api/v1/integrations/{gsc|ga4}/auth-url`` (cu sesiunea
   clientului) si deschide URL-ul Google primit.
2. Clientul isi da consimtamantul, iar Google trimite browserul pe
   ``GET /api/v1/integrations/{gsc|ga4}/callback?code=...&state=...``.
3. Callback-ul schimba codul pe un refresh token, il cripteaza pe
   ``ClientAccount`` si trimite browserul inapoi pe pagina de integrari a
   site-ului, cu ``?conectat=`` sau ``?eroare=`` - coduri, nu texte, ca in URL
   sa nu ajunga niciodata mesaje arbitrare.

Callback-ul nu are sesiunea clientului (e o redirectionare de browser, fara
antetul ``Authorization``): contul vine din starea semnata, emisa la pasul 1
doar pentru contul autentificat (vezi ``security.create_oauth_state``).

Token-urile salvate aici sunt cele pe care le citeste deja agentul PPC pentru
datele organice ale clientului (``jobs/tasks.py::_app_config_for``).
"""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.search_data.google_oauth import (
    build_consent_url,
    exchange_authorization_code,
    exchange_refresh_token,
    revoke_token,
)
from ppc_agent_server.db import get_session
from ppc_agent_server.google_integrations import (
    INTEGRATIONS,
    GoogleIntegration,
    GoogleOAuthClient,
    IntegrationName,
    google_oauth_client,
    list_properties,
    normalize_property_id,
)
from ppc_agent_server.models import ClientAccount, ClientUser
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import (
    IntegrationAuthUrl,
    IntegrationPropertyRead,
    IntegrationsStatus,
    IntegrationState,
    IntegrationUpdate,
)
from ppc_agent_server.security import (
    create_oauth_state,
    decode_oauth_state,
    decrypt_secret,
    encrypt_secret,
)
from ppc_agent_server.settings import get_server_settings

__all__ = ["GoogleOAuthClient", "get_google_oauth_client", "get_google_transport", "router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

#: Pagina din site pe care se intoarce clientul dupa ecranul Google.
SITE_INTEGRATIONS_PATH = "/cont/seo-geo/integrari"

_OAUTH_NOT_CONFIGURED = (
    "Conectarea cu Google nu e configurata pe server: lipsesc "
    "PPC_GOOGLE_OAUTH_CLIENT_ID si PPC_GOOGLE_OAUTH_CLIENT_SECRET (vezi .env.example)."
)


def get_google_oauth_client() -> GoogleOAuthClient | None:
    """Dependinta: clientul OAuth Google, sau ``None`` daca serverul nu il are."""
    return google_oauth_client()


def get_google_transport() -> httpx.BaseTransport | None:
    """Dependinta: transportul HTTP catre Google. ``None`` = retea reala.

    Exista ca testele sa inlocuiasca Google cu un ``httpx.MockTransport`` -
    acelasi tipar ca motorul de audit injectabil din ``seo_geo_agent``.
    """
    return None


GoogleOAuthDep = Annotated[GoogleOAuthClient | None, Depends(get_google_oauth_client)]
TransportDep = Annotated[httpx.BaseTransport | None, Depends(get_google_transport)]
UserDep = Annotated[ClientUser, Depends(get_current_client_user)]
SessionDep = Annotated[Session, Depends(get_session)]


def _account(session: Session, user: ClientUser) -> ClientAccount:
    account = session.get(ClientAccount, user.client_account_id)
    assert account is not None  # garantat de FK, creat impreuna la signup
    return account


def _state(account: ClientAccount, integration: GoogleIntegration) -> IntegrationState:
    return IntegrationState(
        connected=bool(getattr(account, integration.token_field)),
        property_id=getattr(account, integration.property_field),
    )


def _redirect_uri(name: IntegrationName) -> str:
    """Identic la ambii pasi ai fluxului - altfel Google refuza codul."""
    base = get_server_settings().public_api_url.rstrip("/")
    return f"{base}/api/v1/integrations/{name}/callback"


def _back_to_site(**params: str) -> RedirectResponse:
    site = get_server_settings().site_url.rstrip("/")
    return RedirectResponse(
        f"{site}{SITE_INTEGRATIONS_PATH}?{urlencode(params)}", status_code=303
    )


@router.get("", response_model=IntegrationsStatus)
def read_integrations(
    user: UserDep, session: SessionDep, oauth: GoogleOAuthDep
) -> IntegrationsStatus:
    """Ce integrari are clientul conectate si ce proprietate a ales la fiecare."""
    account = _account(session, user)
    return IntegrationsStatus(
        oauth_configured=oauth is not None,
        gsc=_state(account, INTEGRATIONS["gsc"]),
        ga4=_state(account, INTEGRATIONS["ga4"]),
    )


@router.get("/{name}/auth-url", response_model=IntegrationAuthUrl)
def integration_auth_url(
    name: IntegrationName, user: UserDep, oauth: GoogleOAuthDep
) -> IntegrationAuthUrl:
    """URL-ul ecranului de consimtamant Google pentru integrarea ``name``."""
    if oauth is None:
        raise HTTPException(status_code=503, detail=_OAUTH_NOT_CONFIGURED)
    try:
        state = create_oauth_state(user.client_account_id, name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return IntegrationAuthUrl(
        auth_url=build_consent_url(
            client_id=oauth.client_id,
            redirect_uri=_redirect_uri(name),
            scopes=INTEGRATIONS[name].scopes,
            state=state,
        )
    )


@router.get("/{name}/callback", response_class=RedirectResponse, status_code=303)
def integration_callback(
    name: IntegrationName,
    session: SessionDep,
    oauth: GoogleOAuthDep,
    transport: TransportDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Pasul 2 al fluxului OAuth: Google trimite aici browserul clientului.

    Raspunde MEREU cu o redirectionare catre site - clientul e in browser, nu
    intr-un client de API; un JSON de eroare l-ar lasa pe o pagina goala.
    """
    if error:
        reason = "acces_refuzat" if error == "access_denied" else "eroare_google"
        return _back_to_site(eroare=reason, integrare=name)
    if not code or not state:
        return _back_to_site(eroare="raspuns_incomplet", integrare=name)
    try:
        account_id = decode_oauth_state(state, name)
    except jwt.PyJWTError:
        return _back_to_site(eroare="sesiune_expirata", integrare=name)
    except RuntimeError:
        return _back_to_site(eroare="server_neconfigurat", integrare=name)
    if oauth is None:
        return _back_to_site(eroare="server_neconfigurat", integrare=name)

    account = session.get(ClientAccount, account_id)
    if account is None:
        return _back_to_site(eroare="cont_inexistent", integrare=name)

    try:
        refresh_token = exchange_authorization_code(
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            code=code,
            redirect_uri=_redirect_uri(name),
            transport=transport,
        )
    except (SetupRequiredError, ProviderError) as exc:
        logger.warning("conectarea %s a esuat pentru contul %s: %s", name, account_id, exc)
        return _back_to_site(eroare="schimb_esuat", integrare=name)

    try:
        encrypted = encrypt_secret(refresh_token)
    except RuntimeError:
        return _back_to_site(eroare="server_neconfigurat", integrare=name)
    setattr(account, INTEGRATIONS[name].token_field, encrypted)
    session.add(account)
    session.commit()
    return _back_to_site(conectat=name)


@router.get("/{name}/properties", response_model=list[IntegrationPropertyRead])
def integration_properties(
    name: IntegrationName,
    user: UserDep,
    session: SessionDep,
    oauth: GoogleOAuthDep,
    transport: TransportDep,
) -> list[IntegrationPropertyRead]:
    """Proprietatile din contul Google conectat, ca clientul sa aleaga din lista."""
    integration = INTEGRATIONS[name]
    token_enc = getattr(_account(session, user), integration.token_field)
    if not token_enc:
        raise HTTPException(
            status_code=409,
            detail=f"Conecteaza intai contul Google pentru {integration.label}.",
        )
    if oauth is None:
        raise HTTPException(status_code=503, detail=_OAUTH_NOT_CONFIGURED)

    reconnect = f"Google a refuzat accesul la {integration.label} - reconecteaza contul."
    try:
        access_token = exchange_refresh_token(
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            refresh_token=decrypt_secret(token_enc),
            transport=transport,
            missing_message=_OAUTH_NOT_CONFIGURED,
        )
    except (SetupRequiredError, InvalidToken) as exc:
        raise HTTPException(status_code=409, detail=reconnect) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        options = list_properties(integration, access_token, transport=transport)
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nu am putut citi proprietatile din {integration.label}: {exc}",
        ) from exc
    return [IntegrationPropertyRead(id=option.id, label=option.label) for option in options]


@router.patch("/{name}", response_model=IntegrationState)
def update_integration(
    name: IntegrationName, payload: IntegrationUpdate, user: UserDep, session: SessionDep
) -> IntegrationState:
    """Proprietatea aleasa - din lista de mai sus sau scrisa de mana."""
    integration = INTEGRATIONS[name]
    try:
        value = normalize_property_id(integration, payload.property_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    account = _account(session, user)
    setattr(account, integration.property_field, value)
    session.add(account)
    session.commit()
    session.refresh(account)
    return _state(account, integration)


@router.delete("/{name}", status_code=204)
def disconnect_integration(
    name: IntegrationName, user: UserDep, session: SessionDep, transport: TransportDep
) -> Response:
    """Deconectare: revoca token-ul la Google si sterge token-ul si proprietatea."""
    integration = INTEGRATIONS[name]
    account = _account(session, user)
    token_enc = getattr(account, integration.token_field)
    if token_enc:
        try:
            revoke_token(decrypt_secret(token_enc), transport=transport)
        except (InvalidToken, RuntimeError):
            logger.warning("token %s ilizibil la deconectare, contul %s", name, account.id)
    setattr(account, integration.token_field, "")
    setattr(account, integration.property_field, "")
    session.add(account)
    session.commit()
    return Response(status_code=204)
