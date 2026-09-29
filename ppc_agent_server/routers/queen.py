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
si filtreaza fragmentele web ale Researcher-ului. Tot doar citeste. Cu
``Accept: text/event-stream`` raspunsul vine in flux (Server-Sent Events): etapele,
fiecare parere cand e gata, sinteza Reginei token cu token (``token`` - o ciorna) si,
la final, ``reply`` - raspunsul valabil, acelasi ``CouncilReply`` ca varianta JSON,
care inlocuieste ciorna (poate fi cel determinist, daca modelul pica sau scrie ceva
ce nu e in date). Pe CPU, modelul local poate scrie minute intregi: cat timp curg
tokeni, clientul ii vede; circuit-breaker-ul sare doar fara niciun token in primele
secunde (``OLLAMA_FIRST_TOKEN_TIMEOUT``).

``GET /api/v1/queen/technician`` - raportul Tehnicianului (``services/technician.py``):
tracking-ul conversiilor, viteza pe mobil (cu datele CrUX) si ultimul audit tehnic
SEO/GEO, verde/rosu, cu reparatiile. Determinist, fara LLM, doar citeste.

``GET /api/v1/queen/memory`` - memoria consiliului, completa (``services/memory.py``):
consiliul primeste doar ultimele 5 intrari; aici e tot istoricul, la cerere.

``GET /api/v1/queen/market`` - contextul pietei al Researcher-ului
(``services/researcher.py``): interesul de cautare din Google Trends si cautarea pe
web, amandoua reale, pe nisa si orasul clientului (fragmentele verificate de Jev,
cand e configurat). Licitatia nu are inca sursa. Poate dura cateva secunde (cache pe
zi).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from ppc_agent_server.db import get_engine, get_session
from ppc_agent_server.models import ClientUser
from ppc_agent_server.rate_limit import CHAT_BURST, CHAT_HOURLY, too_many_requests
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.council import (
    MAX_QUESTION_CHARS,
    CouncilEvent,
    CouncilListener,
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
    GoogleOrganicTraffic,
    OrganicTrafficSource,
    SearchConsoleIntent,
    SeoIntentSource,
)
from ppc_agent_server.services.researcher import MarketDirective, MarketResearcher
from ppc_agent_server.services.technician import TechnicianDirective, evaluate_technical_health
from ppc_agent_server.settings import get_server_settings

logger = logging.getLogger("ppc_agent_server.routers.queen")

router = APIRouter(prefix="/api/v1/queen", tags=["queen-agent"])

SSE_MEDIA_TYPE = "text/event-stream"
#: Cat taca fluxul pana trimite un comentariu SSE: pe CPU, consiliul poate delibera
#: minute intregi, iar proxy-urile inchid conexiunile mute.
SSE_KEEPALIVE_SECONDS = 15.0
STREAM_ERROR = "Consiliul nu a putut răspunde acum. Încearcă din nou în câteva minute."


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


def get_organic_traffic() -> OrganicTrafficSource:
    """Dependinta: traficul din GA4 si Search Console (live). Injectabila in teste."""
    return GoogleOrganicTraffic()


@router.get("/client-message", response_model=CmoMessage)
def read_client_message(
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    voice: Annotated[TextGenerator | None, Depends(get_cmo_voice)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
    traffic: Annotated[OrganicTrafficSource, Depends(get_organic_traffic)],
) -> CmoMessage:
    """Mesajul Reginei catre client: publicul ideal, ce nu rezoneaza si ce s-a propus."""
    signals = DbBrandSignals(session, seo_intent=seo_intent, traffic=traffic)
    queen = BrandStrategist(signals, voice=voice)
    directive = queen.evaluate_brand_alignment(user.client_account_id)
    return queen.generate_cmo_message(user.client_account_id, directive)


class ChatRequest(BaseModel):
    """Intrebarea clientului pentru Regina."""

    message: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return clean_question(value)


def _deliberate(
    session: Session,
    client_account_id: int,
    message: str,
    *,
    voice: TextGenerator | None,
    system_one: LLMRouter | None,
    seo_intent: SeoIntentSource,
    traffic: OrganicTrafficSource,
    on_event: CouncilListener | None = None,
) -> CouncilReply:
    """Directiva Reginei, apoi consiliul pe intrebare - acelasi drum, cu sau fara flux."""
    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent, traffic=traffic))
    directive = queen.evaluate_brand_alignment(client_account_id)
    council = QueenCouncil(
        DbFinancialSignals(session),
        technical=DbTechnicalSignals(session),
        market=ClientMarketSignals(session, verifier=system_one),
        memory=DbMemory(session),
        voice=voice,
        scorer=system_one,
    )
    return council.evaluate_client_query(message, directive, on_event=on_event)


def _sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    """Un eveniment SSE; JSON-ul e pe un singur rand, deci un singur camp ``data``."""
    if isinstance(data, BaseModel):
        payload = data.model_dump_json()
    else:
        payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _event_sse(event: CouncilEvent) -> str:
    if event.kind == "opinion" and event.opinion is not None:
        return _sse("opinion", event.opinion)
    if event.kind == "rebuttal" and event.rebuttal is not None:
        return _sse("rebuttal", event.rebuttal)
    if event.kind == "token":
        return _sse("token", {"text": event.text})
    return _sse("stage", {"stage": event.stage})


_Done = object()


def council_event_stream(
    run: Callable[[CouncilListener], CouncilReply],
    *,
    keepalive: float = SSE_KEEPALIVE_SECONDS,
) -> Iterator[str]:
    """Deliberarea ca flux SSE: ``run`` merge intr-un fir, evenimentele vin printr-o coada.

    Ordinea: ``stage``/``opinion``/``rebuttal``/``token`` pe masura ce se intampla, apoi
    ``reply`` (raspunsul valabil) sau ``error``, apoi ``done``. Un client care inchide
    conexiunea nu opreste consiliul: raspunsul se termina si memoria se scrie.
    """
    events: queue.Queue[object] = queue.Queue()

    def worker() -> None:
        try:
            events.put(run(events.put))
        except Exception as exc:  # orice ar fi, clientul primeste un final, nu o asteptare
            events.put(exc)
        finally:
            events.put(_Done)

    threading.Thread(target=worker, name="consiliu-sse", daemon=True).start()
    while True:
        try:
            item = events.get(timeout=keepalive)
        except queue.Empty:
            yield ": consiliul deliberează\n\n"
            continue
        if item is _Done:
            break
        if isinstance(item, CouncilReply):
            yield _sse("reply", item)
        elif isinstance(item, CouncilEvent):
            yield _event_sse(item)
        elif isinstance(item, Exception):
            logger.error("[Regina] deliberarea in flux a picat: %r", item, exc_info=item)
            yield _sse("error", {"detail": STREAM_ERROR})
    yield _sse("done", {})


@router.post(
    "/chat",
    response_model=CouncilReply,
    responses={200: {"content": {SSE_MEDIA_TYPE: {"schema": {"type": "string"}}}}},
)
def chat_with_queen(
    body: ChatRequest,
    request: Request,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    voice: Annotated[TextGenerator | None, Depends(get_cmo_voice)],
    system_one: Annotated[LLMRouter | None, Depends(get_system_one)],
    seo_intent: Annotated[SeoIntentSource, Depends(get_seo_intent)],
    traffic: Annotated[OrganicTrafficSource, Depends(get_organic_traffic)],
) -> CouncilReply | StreamingResponse:
    """Raspunsul Reginei la o intrebare libera, dupa deliberarea consiliului (``reply``).

    Cu ``Accept: text/event-stream``: aceeasi deliberare, in flux (vezi docstring-ul
    modulului). Limitat per client (``rate_limit.py``): fiecare mesaj costa pana la
    sase generari pe modelul local, cateva apeluri Jev si tine un fir ocupat - 429
    peste rafala sau plafonul orar, inainte sa inceapa vreun flux.
    """
    key = f"client:{user.client_account_id}"
    wait = CHAT_BURST.retry_after(key) or CHAT_HOURLY.retry_after(key)
    if wait is not None:
        raise too_many_requests(wait, "Ai trimis multe întrebări într-un timp scurt.")
    CHAT_BURST.hit(key)
    CHAT_HOURLY.hit(key)

    client_account_id = user.client_account_id
    if SSE_MEDIA_TYPE not in request.headers.get("accept", ""):
        return _deliberate(
            session,
            client_account_id,
            body.message,
            voice=voice,
            system_one=system_one,
            seo_intent=seo_intent,
            traffic=traffic,
        )

    def run(on_event: CouncilListener) -> CouncilReply:
        # Sesiune proprie: fluxul traieste dupa ce cererea si-a inchis dependintele.
        on_event(CouncilEvent("stage", stage="context"))
        with Session(get_engine()) as own:
            return _deliberate(
                own,
                client_account_id,
                body.message,
                voice=voice,
                system_one=system_one,
                seo_intent=seo_intent,
                traffic=traffic,
                on_event=on_event,
            )

    return StreamingResponse(
        council_event_stream(run),
        media_type=SSE_MEDIA_TYPE,
        # Fara buffer in nginx si fara cache: tokenii pleaca pe masura ce vin.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    traffic: Annotated[OrganicTrafficSource, Depends(get_organic_traffic)],
) -> MarketDirective:
    """Contextul pietei: Google Trends si cautarea pe web, pe nisa clientului."""
    queen = BrandStrategist(DbBrandSignals(session, seo_intent=seo_intent, traffic=traffic))
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
