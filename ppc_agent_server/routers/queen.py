"""Regina vorbeste cu clientul: mesajul CMO si chatul deliberat de consiliu.

Modelele vin din ruterul hibrid (``services/llm_client.py``): textul il scrie
Ollama, local (Sistemul 2, ``OLLAMA_HOST``); deciziile structurate le ia Jev
(Sistemul 1, ``JEV_API_KEY``). Fara ele - sau cand pica - totul cade pe varianta
determinista, deci rutele raspund mereu 200.

``GET /api/v1/queen/client-message`` - Regina explica deciziile ei clientului.
Doar citeste: evalueaza directiva clientului autentificat (determinist, fara
LLM) si o formuleaza ca un mesaj de consultant. Vocea e Ollama; fara el - sau
cand modelul pica ori scrie ceva ce nu e in date - mesajul vine dintr-un template
intern. Nu creeaza propuneri si nu schimba nimic: propunerile le face jobul de
noapte (``jobs/brand_alignment.py``).

``POST /api/v1/queen/chat`` - o intrebare libera a clientului. Regina nu raspunde
direct: isi consulta consiliul (strategia de brand, CFO-ul, Tehnicianul, Researcher-ul
si CPO-ul, vezi ``services/council.py``), iar decizia - ce trece, ce se taie, ce
opreste veto-ul Tehnicianului - e determinista. Jev noteaza mutarile CPO-ului (RICE)
si filtreaza fragmentele web ale Researcher-ului. Tot doar citeste.

``GET /api/v1/queen/technician`` - raportul Tehnicianului (``services/technician.py``):
tracking-ul conversiilor si viteza pe mobil, verde/rosu, cu reparatiile. Determinist,
fara LLM, doar citeste.

``GET /api/v1/queen/memory`` - memoria consiliului, completa (``services/memory.py``):
consiliul primeste doar ultimele 5 intrari; aici e tot istoricul, la cerere.

``GET /api/v1/queen/market`` - contextul pietei al Researcher-ului
(``services/researcher.py``): cautarea pe web, reala, pe nisa si orasul clientului
(fragmentele verificate de Jev, cand e configurat), plus licitatia si cererea -
acestea demonstrative (``is_demo: true``) pana se conecteaza surse. Cautarea pe web
poate dura cateva secunde (cache pe zi).
"""

from __future__ import annotations

from datetime import datetime
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
from ppc_agent_server.services.llm_client import LLMRouter, llm_router_from_settings
from ppc_agent_server.services.memory import MemoryOutcome, memory_line
from ppc_agent_server.services.queen_agent import (
    BrandStrategist,
    CmoMessage,
    TextGenerator,
    _utc_now,
)
from ppc_agent_server.services.queen_signals import (
    ClientMarketSignals,
    DbBrandSignals,
    DbFinancialSignals,
    DbMemory,
    DbTechnicalSignals,
    SearchConsoleIntent,
    SeoIntentSource,
)
from ppc_agent_server.services.researcher import MarketDirective, MarketResearcher
from ppc_agent_server.services.technician import TechnicianDirective, evaluate_technical_health
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/queen", tags=["queen-agent"])


def get_llm_router() -> LLMRouter:
    """Dependinta: ruterul hibrid din ``.env`` - Jev (Sistemul 1) si Ollama (Sistemul 2)."""
    return llm_router_from_settings(get_server_settings())


def get_cmo_voice(router: Annotated[LLMRouter, Depends(get_llm_router)]) -> TextGenerator | None:
    """Dependinta: vocea - Ollama, prin ``generate_text_local`` - sau ``None`` (-> template)."""
    return router.voice


def get_system_one(router: Annotated[LLMRouter, Depends(get_llm_router)]) -> LLMRouter | None:
    """Dependinta: deciziile structurate (Jev), sau ``None`` (-> reguli fixe)."""
    return router if router.ready("score") else None


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
    system_one: Annotated[LLMRouter | None, Depends(get_system_one)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
) -> CouncilReply:
    """Raspunsul Reginei la o intrebare libera, dupa deliberarea consiliului (``reply``).

    Limitat per client (``rate_limit.py``): fiecare mesaj costa pana la sase
    generari pe modelul local, cateva apeluri Jev si tine un fir ocupat - 429 peste
    rafala sau plafonul orar.
    """
    key = f"client:{user.client_account_id}"
    wait = CHAT_BURST.retry_after(key) or CHAT_HOURLY.retry_after(key)
    if wait is not None:
        raise too_many_requests(wait, "Ai trimis multe întrebări într-un timp scurt.")
    CHAT_BURST.hit(key)
    CHAT_HOURLY.hit(key)

    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent))
    directive = queen.evaluate_brand_alignment(user.client_account_id)
    council = QueenCouncil(
        DbFinancialSignals(session),
        technical=DbTechnicalSignals(session),
        market=ClientMarketSignals(session, verifier=system_one),
        memory=DbMemory(session),
        voice=voice,
        scorer=system_one,
    )
    return council.evaluate_client_query(body.message, directive)


@router.get("/technician", response_model=TechnicianDirective)
def read_technician_report(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> TechnicianDirective:
    """Raportul Tehnicianului: tracking verde/rosu, viteza pe mobil, veto si reparatii."""
    signals = DbTechnicalSignals(session).load(user.client_account_id)
    return evaluate_technical_health(user.client_account_id, signals, generated_at=_utc_now())


@router.get("/market", response_model=MarketDirective)
def read_market_context(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
    system_one: Annotated[LLMRouter | None, Depends(get_system_one)],
) -> MarketDirective:
    """Contextul pietei: cautarea pe web (reala) + licitatia si cererea (demonstrative azi)."""
    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent))
    directive = queen.evaluate_brand_alignment(user.client_account_id)
    queries = [query for segment in directive.segments for query in segment.sample_queries]
    market = ClientMarketSignals(session, verifier=system_one)
    researcher = MarketResearcher(market, clock=_utc_now)
    return researcher.evaluate_market_context(user.client_account_id, queries)


class MemoryRecord(BaseModel):
    """O intrare din memoria consiliului, cu randul pe care il vede si consiliul."""

    at: datetime
    agent_role: str
    topic: str
    decision: str
    observation: str
    outcome: MemoryOutcome
    line: str


@router.get("/memory", response_model=list[MemoryRecord])
def read_council_memory(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[MemoryRecord]:
    """Tot istoricul consiliului (ultimele 50 de intrari), cele mai recente primele."""
    now = _utc_now()
    return [
        MemoryRecord(
            at=entry.at,
            agent_role=entry.role,
            topic=entry.topic,
            decision=entry.decision,
            observation=entry.observation,
            outcome=entry.outcome,
            line=memory_line(entry, now),
        )
        for entry in DbMemory(session).recall(user.client_account_id, limit=50)
    ]
