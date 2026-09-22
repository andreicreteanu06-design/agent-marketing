"""Autentificare self-service pentru clientii finali ai agentiei.

Distinct de ``routers/auth.py`` (schimb OAuth pe conturile de reclame, stub) si
de ``ppc_agent_server.auth`` (autentificarea AGENTIEI, prin cheie API) - aici
e vizitatorul care isi creeaza cont pe site-ul public (``POST /signup``) si se
autentifica ulterior prin parola (``POST /login``), ca sa-si conecteze
conturile de reclame (``PATCH /me/credentials``).
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session, select

from ppc_agent_server.db import get_session
from ppc_agent_server.models import ClientAccount, ClientUser, Tenant
from ppc_agent_server.schemas import (
    ClientCredentialsUpdate,
    ClientCredentialsUpdateResponse,
    ClientLoginRequest,
    ClientMeResponse,
    ClientSignupRequest,
    ClientTokenResponse,
)
from ppc_agent_server.security import (
    create_client_token,
    decode_client_token,
    encrypt_secret,
    hash_password,
    verify_password,
)
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1", tags=["client-auth"])


def _require_jwt_configured() -> None:
    """503 devreme daca ``JWT_SECRET_KEY`` lipseste - verificat ÎNAINTE de a crea
    randuri DB in ``signup`` (altfel ar ramane un cont orfan, fara nicio cale
    de a obtine vreodata un token pentru el)."""
    if not get_server_settings().jwt_secret_key:
        raise HTTPException(status_code=503, detail="JWT_SECRET_KEY nu e configurat pe server")


def get_current_client_user(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> ClientUser:
    """Dependinta FastAPI: rezolva clientul autentificat din antetul ``Authorization``.

    Oglindeste ``ppc_agent_server.auth.get_current_tenant``, dar pe token JWT
    (sesiune de client), nu pe cheie API (agentie) - cele doua mecanisme
    raman complet separate.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="lipseste antetul 'Authorization: Bearer <token>'"
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = decode_client_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="token invalid sau expirat") from exc
    except RuntimeError as exc:
        # JWT_SECRET_KEY neconfigurat - eroare de operare server, nu a
        # apelantului; nu trebuie sa se scurga ca 500 brut (vezi RuntimeError
        # din security.decode_client_token).
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    user = session.get(ClientUser, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="utilizator inexistent")
    return user


@router.post("/signup", response_model=ClientTokenResponse, status_code=201)
def signup(
    payload: ClientSignupRequest, session: Annotated[Session, Depends(get_session)]
) -> ClientTokenResponse:
    """Creeaza un cont de client nou (``ClientAccount`` + ``ClientUser``).

    Contul e atasat tenant-ului configurat in ``AGENCY_TENANT_ID`` - produsul
    e single-agentie azi (vezi ``settings.py``), nu exista alegere de agentie
    la semnare.
    """
    _require_jwt_configured()
    settings = get_server_settings()
    if settings.agency_tenant_id is None:
        raise HTTPException(
            status_code=503, detail="AGENCY_TENANT_ID nu e configurat pe server"
        )
    tenant = session.get(Tenant, settings.agency_tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=503, detail="tenant-ul configurat (AGENCY_TENANT_ID) nu exista"
        )

    existing = session.exec(
        select(ClientUser).where(ClientUser.email == payload.email)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="exista deja un cont cu acest email")

    account = ClientAccount(tenant_id=tenant.id, name=payload.name)
    session.add(account)
    session.commit()
    session.refresh(account)

    user = ClientUser(
        client_account_id=account.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return ClientTokenResponse(access_token=create_client_token(user.id))  # type: ignore[arg-type]


@router.post("/login", response_model=ClientTokenResponse)
def login(
    payload: ClientLoginRequest, session: Annotated[Session, Depends(get_session)]
) -> ClientTokenResponse:
    """Autentifica un client existent prin email + parola.

    Acelasi mesaj de eroare pentru "email inexistent" si "parola gresita"
    deliberat - nu confirmam catre un apelant neautorizat daca adresa e
    inregistrata (previne enumerarea de conturi).
    """
    _require_jwt_configured()
    user = session.exec(select(ClientUser).where(ClientUser.email == payload.email)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="email sau parola incorecte")

    return ClientTokenResponse(access_token=create_client_token(user.id))  # type: ignore[arg-type]


@router.get("/me", response_model=ClientMeResponse)
def read_me(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientMeResponse:
    """Identitatea + contul clientului autentificat curent."""
    account = session.get(ClientAccount, user.client_account_id)
    assert account is not None  # garantat de FK unic, creat impreuna la signup
    return ClientMeResponse(
        user=user,  # type: ignore[arg-type]
        account=account,  # type: ignore[arg-type]
        google_ads_connected=bool(account.google_ads_refresh_token_enc),
        meta_connected=bool(account.meta_access_token_enc),
        tiktok_connected=bool(account.tiktok_access_token_enc),
        chatgpt_connected=bool(account.chatgpt_ads_api_key_enc),
    )


@router.patch("/me/credentials", response_model=ClientCredentialsUpdateResponse)
def update_my_credentials(
    payload: ClientCredentialsUpdate,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ClientCredentialsUpdateResponse:
    """Cripteaza si salveaza cheile API trimise - doar campurile prezente.

    ``client_account_id`` vine din token-ul autenticat, nu dintr-un parametru
    de URL - un client nu poate, nici din greseala, sa scrie pe contul
    altcuiva (nu exista nicio cale sa specifice alt ID).
    """
    account = session.get(ClientAccount, user.client_account_id)
    assert account is not None

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field_name, raw_value in updates.items():
        setattr(account, f"{field_name}_enc", encrypt_secret(raw_value))

    session.add(account)
    session.commit()
    return ClientCredentialsUpdateResponse(updated_fields=list(updates.keys()))
