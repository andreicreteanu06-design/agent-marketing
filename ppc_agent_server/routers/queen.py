"""Regina vorbeste cu clientul: mesajul CMO si chatul deliberat de consiliu.

``GET /api/v1/queen/client-message`` - Regina explica deciziile ei clientului.
Doar citeste: evalueaza directiva clientului autentificat (determinist, fara
LLM) si o formuleaza ca un mesaj de consultant. Vocea e Hugging Face cand
``HUGGINGFACE_API_KEY`` e setat; altfel - sau cand modelul pica ori scrie ceva
ce nu e in date - mesajul vine dintr-un template intern, deci ruta raspunde
mereu 200 cu un mesaj utilizabil. Nu creeaza propuneri si nu schimba nimic:
propunerile le face jobul de noapte (``jobs/brand_alignment.py``).

``POST /api/v1/queen/chat`` - o intrebare libera a clientului. Regina nu raspunde
direct: isi consulta consiliul (strategia de brand + CFO-ul, vezi
``services/council.py``), iar decizia - ce trece, ce se taie - e determinista.
Tot doar citeste; raspunde 200 si fara Hugging Face.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from ppc_agent_server.db import get_session
from ppc_agent_server.models import ClientUser
from ppc_agent_server.rate_limit import CHAT_BURST, CHAT_HOURLY, too_many_requests
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.council import (
    MAX_QUESTION_CHARS,
    CouncilReply,
    QueenCouncil,
    clean_question,
)
from ppc_agent_server.services.hf_client import hf_client_from_settings
from ppc_agent_server.services.queen_agent import BrandStrategist, CmoMessage, TextGenerator
from ppc_agent_server.services.queen_signals import (
    DbBrandSignals,
    DbFinancialSignals,
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


class ChatRequest(BaseModel):
    """Intrebarea clientului pentru Regina."""

    message: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return clean_question(value)


@router.post("/chat", response_model=CouncilReply)
def chat_with_queen(
    body: ChatRequest,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    voice: Annotated[TextGenerator | None, Depends(get_cmo_voice)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
) -> CouncilReply:
    """Raspunsul Reginei la o intrebare libera, dupa deliberarea consiliului (``reply``).

    Limitat per client (``rate_limit.py``): fiecare mesaj costa pana la trei
    apeluri Hugging Face si tine un fir ocupat - 429 peste rafala sau plafonul orar.
    """
    key = f"client:{user.client_account_id}"
    wait = CHAT_BURST.retry_after(key) or CHAT_HOURLY.retry_after(key)
    if wait is not None:
        raise too_many_requests(wait, "Ai trimis multe întrebări într-un timp scurt.")
    CHAT_BURST.hit(key)
    CHAT_HOURLY.hit(key)

    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent))
    directive = queen.evaluate_brand_alignment(user.client_account_id)
    council = QueenCouncil(DbFinancialSignals(session), voice=voice)
    return council.evaluate_client_query(body.message, directive)
