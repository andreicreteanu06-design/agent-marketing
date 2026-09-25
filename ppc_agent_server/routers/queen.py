"""``GET /api/v1/queen/client-message`` - Regina explica deciziile ei clientului.

Doar citeste: evalueaza directiva clientului autentificat (determinist, fara
LLM) si o formuleaza ca un mesaj de consultant. Vocea e Hugging Face cand
``HUGGINGFACE_API_KEY`` e setat; altfel - sau cand modelul pica ori scrie ceva
ce nu e in date - mesajul vine dintr-un template intern, deci ruta raspunde
mereu 200 cu un mesaj utilizabil. Nu creeaza propuneri si nu schimba nimic:
propunerile le face jobul de noapte (``jobs/brand_alignment.py``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ppc_agent_server.db import get_session
from ppc_agent_server.models import ClientUser
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.hf_client import hf_client_from_settings
from ppc_agent_server.services.queen_agent import BrandStrategist, CmoMessage, TextGenerator
from ppc_agent_server.services.queen_signals import (
    DbBrandSignals,
    SearchConsoleIntent,
    SeoIntentSource,
)
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/queen", tags=["queen-agent"])


def get_cmo_voice() -> TextGenerator | None:
    """Dependinta: clientul Hugging Face din ``.env``, sau ``None`` (-> template)."""
    return hf_client_from_settings(get_server_settings())


def get_seo_intent() -> SeoIntentSource:
    """Dependinta: cautarile organice (Search Console live). Injectabila in teste."""
    return SearchConsoleIntent()


@router.get("/client-message", response_model=CmoMessage)
def read_client_message(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    voice: Annotated[TextGenerator | None, Depends(get_cmo_voice)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
) -> CmoMessage:
    """Mesajul Reginei catre client: publicul ideal, ce nu rezoneaza si ce s-a propus."""
    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent), voice=voice)
    directive = queen.evaluate_brand_alignment(user.client_account_id)
    return queen.generate_cmo_message(user.client_account_id, directive)
