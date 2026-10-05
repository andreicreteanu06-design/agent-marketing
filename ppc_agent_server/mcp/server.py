"""Serverul MCP "Arting_Hybrid_Engine" si cele patru unelte ale lui.

Doua transporturi, acelasi server: SSE in aplicatia web (``routers/mcp_router.py``,
contul vine din token) si stdio pentru aplicatiile locale (``ppc_agent_server/
mcp_server.py``, contul vine din ``MCP_CLIENT_ACCOUNT_ID``).

Contextul de client NU e un parametru al uneltelor, ci vine din conexiunea
autentificata (:data:`current_client_account_id`). Doua motive, ambele serioase:

- daca ar fi parametru, un agent ar putea cere datele ALTUI client scriind alt
  id. Aici nu poate: id-ul e legat de token-ul cu care s-a deschis conexiunea;
- uneltele raman fara stare - nu tin nimic intre apeluri, iar acelasi proces
  poate servi simultan conexiuni ale mai multor clienti fara sa le amestece.

``contextvars`` (nu o variabila globala) exact de asta: fiecare conexiune SSE
ruleaza in task-ul ei asyncio, iar valoarea seta in task-ul acela nu se vede din
celelalte.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from decimal import Decimal
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError
from sqlmodel import Session, select

from ppc_agent.search_data.insights import CannibalizationDetector, SeoOpportunityFinder
from ppc_agent_server.db import get_engine
from ppc_agent_server.hybrid_queries import (
    DEFAULT_WINDOW_DAYS,
    load_organic_positions,
    load_paid_terms,
)
from ppc_agent_server.models import ChangeOp, ChangeStatus, ClientAccount, ProposedChange
from ppc_agent_server.services.creative_context import PerformanceFeedback
from ppc_agent_server.services.creative_memory import (
    FeedbackError,
    account_lessons,
    record_feedback,
)
from ppc_agent_server.settings import get_server_settings
from ppc_agent_server.spend_guard import committed_daily_spend

SERVER_NAME = "Arting_Hybrid_Engine"

#: Contul clientului pentru conexiunea MCP curenta. Setat de middleware-ul de
#: autentificare din ``routers/mcp_router.py``, la deschiderea conexiunii.
_current_client_account_id: ContextVar[int | None] = ContextVar(
    "mcp_client_account_id", default=None
)


class NotAuthenticatedError(RuntimeError):
    """Unealta a fost apelata fara un client autentificat pe conexiune."""


def set_client_account_id(client_account_id: int) -> Token[int | None]:
    """Leaga conexiunea curenta de un cont de client. Intoarce token-ul de reset."""
    return _current_client_account_id.set(client_account_id)


def reset_client_account_id(token: Token[int | None]) -> None:
    """Desface legatura facuta de :func:`set_client_account_id`.

    Necesar, nu cosmetic: acelasi task poate servi alta cerere dupa asta, iar
    o valoare ramasa agatata ar da datele unui client in raspunsul altuia.
    """
    _current_client_account_id.reset(token)


def current_client_account_id() -> int:
    """Contul clientului de pe conexiunea curenta.

    Raises:
        NotAuthenticatedError: conexiunea nu a trecut prin autentificare - un
            bug de montare, nu o situatie normala.
    """
    account_id = _current_client_account_id.get()
    if account_id is None:
        raise NotAuthenticatedError(
            "conexiunea MCP nu are un client autentificat asociat"
        )
    return account_id


def build_server() -> MCPServer[None]:
    """Construieste serverul MCP cu cele sase unelte.

    Functie, nu obiect global, din acelasi motiv ca ``create_app()``: se poate
    instantia izolat intr-un test, fara sa ramana stare intre ele.
    """
    server: MCPServer[None] = MCPServer(
        name=SERVER_NAME,
        title="Arting - motor hibrid PPC + SEO",
        instructions=(
            "Unelte peste datele reale de cautare ale unui client: pozitii organice "
            "(Search Console si OpenSERP) imbinate cu cheltuiala si conversiile din "
            "Google Ads. Uneltele de citire raspund direct. Unealta de propunere NU "
            "aplica nicio modificare - creeaza o propunere care asteapta aprobare "
            "umana in interfata."
        ),
    )

    @server.tool(
        name="get_cannibalization_insights",
        title="Canibalizare: platim pentru ce detinem deja organic",
        description=(
            "Termeni de cautare pe care site-ul e deja in primele 3 pozitii organice, "
            "dar pentru care se cheltuie in continuare in Google Ads. Fiecare rezultat "
            "include pozitia organica, cheltuiala si conversiile, plus economia "
            "POTENTIALA - limita superioara, nu garantata: o parte din click-uri nu "
            "s-ar muta pe organic. Foloseste-le ca lista de teste de oprire, nu ca "
            "ordin de taiere a bugetului."
        ),
    )
    def get_cannibalization_insights(days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
        """Args:
        days: Fereastra de analiza, in zile (implicit 30).
        """
        account_id = current_client_account_id()
        with Session(get_engine()) as session:
            findings = CannibalizationDetector().find(
                load_paid_terms(session, account_id, days=days),
                load_organic_positions(session, account_id),
            )
        return {
            "window_days": days,
            "count": len(findings),
            "total_potential_saving": str(
                sum((item.potential_monthly_saving for item in findings), start=Decimal("0"))
            ),
            "items": [
                {
                    "term": item.term,
                    "organic_position": item.organic_position,
                    "paid_clicks": item.paid_clicks,
                    "paid_cost": str(item.paid_cost),
                    "paid_conversions": item.paid_conversions,
                    "potential_saving": str(item.potential_monthly_saving),
                }
                for item in findings
            ],
        }

    @server.tool(
        name="get_seo_opportunities",
        title="Oportunitati SEO: termeni care convertesc platit, fara organic",
        description=(
            "Termeni care aduc conversii in Google Ads, dar unde site-ul nu se claseaza "
            "organic (peste pozitia 10 sau deloc). Sortati dupa CONVERSII, nu dupa volum "
            "de cautare estimat: un cuvant cu 40.000 de cautari si zero conversii nu "
            "merita continut, unul cu 90 de cautari si 12 conversii merita."
        ),
    )
    def get_seo_opportunities(days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
        """Args:
        days: Fereastra de analiza, in zile (implicit 30).
        """
        account_id = current_client_account_id()
        with Session(get_engine()) as session:
            opportunities = SeoOpportunityFinder().find(
                load_paid_terms(session, account_id, days=days),
                load_organic_positions(session, account_id),
            )
        return {
            "window_days": days,
            "count": len(opportunities),
            "items": [
                {
                    "term": item.term,
                    "paid_conversions": item.paid_conversions,
                    "paid_cost": str(item.paid_cost),
                    "paid_cpa": str(item.paid_cpa) if item.paid_cpa is not None else None,
                    "roas": item.roas,
                    "organic_position": item.organic_position,
                }
                for item in opportunities
            ],
        }

    @server.tool(
        name="get_budget_summary",
        title="Bugetul curent: plafonul zilnic si cat e deja angajat",
        description=(
            "Sumarul bugetului zilnic al clientului, din datele reale ale aplicatiei: "
            "plafonul efectiv (limita clientului, dar niciodata peste plafonul de "
            "siguranta al platformei), bugetele deja angajate (propuneri executate sau "
            "in curs de aplicare), cat mai incape si ce propuneri asteapta aprobarea. "
            "Nu citeste cheltuiala reala din Meta - doar ce a trecut prin aplicatie."
        ),
    )
    def get_budget_summary() -> dict[str, Any]:
        account_id = current_client_account_id()
        with Session(get_engine()) as session:
            account = session.get(ClientAccount, account_id)
            if account is None:
                raise ToolError("contul clientului nu mai exista")
            cap = min(account.max_daily_spend, get_server_settings().max_daily_spend_ron)
            committed = committed_daily_spend(session, account_id)
            pending = session.exec(
                select(ProposedChange).where(
                    ProposedChange.client_account_id == account_id,
                    ProposedChange.status == ChangeStatus.PENDING,
                )
            ).all()
        return {
            "client": account.name,
            "currency": "RON",
            "daily_cap": str(cap),
            "committed_daily_budget": str(committed),
            "remaining_daily_budget": str(max(cap - committed, Decimal("0"))),
            "pending_proposals": len(pending),
            "pending_daily_budget": str(
                sum((change.projected_daily_spend for change in pending), Decimal("0"))
            ),
        }

    @server.tool(
        name="propose_budget_change",
        title="Propune o schimbare de buget (NU o aplica)",
        description=(
            "Creeaza o PROPUNERE de buget zilnic pentru un cuvant cheie si o lasa in "
            "starea 'pending'. NU modifica nimic in contul de reclame si nu poate fi "
            "folosita ca sa aplice ceva: singura cale catre cont trece prin aprobarea "
            "umana din interfata. Intoarce id-ul propunerii, ca sa poata fi urmarita."
        ),
    )
    def propose_budget_change(
        keyword: str, proposed_daily_budget: float, rationale: str
    ) -> dict[str, Any]:
        """Args:
        keyword: Cuvantul cheie sau campania vizata.
        proposed_daily_budget: Bugetul zilnic propus, in moneda contului.
        rationale: De ce - se arata omului care aproba, deci scrie motivul real
            si cifrele pe care se bazeaza, nu o formulare generica.
        """
        account_id = current_client_account_id()
        budget = Decimal(str(proposed_daily_budget))
        if budget < 0:
            # ToolError, nu ValueError: SDK-ul il traduce intr-un rezultat de
            # eroare pe care agentul il poate citi si corecta, in loc sa arunce
            # o exceptie neasteptata in sesiune.
            raise ToolError("bugetul propus nu poate fi negativ")

        with Session(get_engine()) as session:
            change = ProposedChange(
                client_account_id=account_id,
                op=ChangeOp.UPDATE,
                resource=keyword,
                resource_type="keyword_budget",
                after={"daily_budget": str(budget)},
                projected_daily_spend=budget,
                rationale=rationale,
                source_module=f"mcp:{SERVER_NAME}",
                status=ChangeStatus.PENDING,
            )
            session.add(change)
            session.commit()
            session.refresh(change)
            change_id = change.id

        return {
            "proposed_change_id": change_id,
            "status": ChangeStatus.PENDING.value,
            "applied": False,
            "message": (
                "Propunere inregistrata. NU s-a modificat nimic in contul de reclame - "
                "asteapta aprobare umana in interfata."
            ),
        }

    @server.tool(
        name="report_creative_performance",
        title="PPC -> CCO: cum a mers in piata o creativa evaluata",
        description=(
            "Trimite CCO-ului cifrele reale ale unei creative pe care a evaluat-o "
            "(evaluation_id din verdict): afisari, click-uri, vizionari de 3 secunde (doar "
            "video), cheltuiala, venit. Daca CCO-ul a promis mai mult (ex. hook 9/10, dar "
            "hook rate sub 20%) sau mai putin decat a dat piata, se scrie o corectie pe care "
            "o citeste inainte de urmatoarea evaluare pe acest cont. Nu schimba nimic in "
            "contul de reclame."
        ),
    )
    def report_creative_performance(
        evaluation_id: int,
        platform: str,
        ad_id: str,
        window_days: int,
        impressions: int,
        clicks: int,
        spend: float,
        revenue: float,
        conversions: float,
        video_views_3s: int | None = None,
    ) -> dict[str, Any]:
        """Args:
        evaluation_id: Id-ul verdictului CCO (``evaluation_id``).
        platform: ``meta`` sau ``tiktok``.
        ad_id: Anuntul in care a rulat creativa.
        window_days: De cate zile ruleaza.
        video_views_3s: Vizionarile de 3 secunde; doar la video.
        """
        account_id = current_client_account_id()
        with Session(get_engine()) as session:
            account = session.get(ClientAccount, account_id)
            if account is None:
                raise ToolError("contul clientului nu mai exista")
            try:
                feedback = PerformanceFeedback.model_validate(
                    {
                        "evaluation_id": evaluation_id,
                        "platform": platform,
                        "ad_id": ad_id,
                        "window_days": window_days,
                        "metrics": {
                            "impressions": impressions,
                            "clicks": clicks,
                            "video_views_3s": video_views_3s,
                            "spend": str(spend),
                            "revenue": str(revenue),
                            "conversions": conversions,
                        },
                        "break_even_roas": float(account.break_even_roas),
                    }
                )
                lessons = record_feedback(session, account_id, feedback)
            except (ValidationError, FeedbackError) as exc:
                raise ToolError(str(exc)) from exc
        return {
            "metrics": feedback.metrics.model_dump(mode="json"),
            "lessons": [lesson.model_dump() for lesson in lessons],
        }

    @server.tool(
        name="get_creative_lessons",
        title="Ce a invatat CCO-ul din piata pe acest cont",
        description=(
            "Corectiile CCO-ului din ultimele 90 de zile: unde a supraestimat sau subestimat "
            "hook-ul si alinierea mesajului, fata de hook rate, CTR si ROAS reale. CCO-ul "
            "le aplica singur la fiecare evaluare; aici se pot doar citi."
        ),
    )
    def get_creative_lessons() -> dict[str, Any]:
        account_id = current_client_account_id()
        with Session(get_engine()) as session:
            lessons = account_lessons(session, account_id)
        return {"count": len(lessons), "items": [lesson.model_dump() for lesson in lessons]}

    return server
