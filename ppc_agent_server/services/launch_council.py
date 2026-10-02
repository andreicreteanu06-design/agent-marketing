"""Nicio campanie noua fara consiliu: avizul lui, atasat propunerii de lansare.

Inainte, garda consiliului (``council_guard``) prindea lansarile doar in jobul de noapte:
o lansare propusa ziua putea fi aprobata pe loc, fara ca cineva sa fi intrebat CFO-ul
sau Tehnicianul. Acum:

- **la depunere** (``POST /campaigns/propose_launch``): consiliul delibereaza pe lansare
  cu toate datele clientului (brand, bani, tehnic, piata, oferta, memoria) - exact ca in
  chat. Avizul (decizia, ce a taiat, veto-ul, parerile) intra in ``before["council"]``,
  langa brief; iar daca dupa deliberare exista un veto al Tehnicianului sau CFO-ul
  opreste un cont care pierde bani dovedit, propunerea se scrie direct ``BLOCKED``, cu
  motivul. Rezerva CFO-ului pe un cont fara date ("nu stim inca ce functioneaza") ramane
  in aviz, dar nu opreste un prim test in plafonul zilnic - altfel un client nou n-ar
  putea lansa niciodata;
- **la aprobare**: fara aviz (propunere veche) - 409, se propune din nou; cu aviz, dar cu
  o restrictie aparuta intre timp - 409 cu motivul.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from ppc_agent_server.jobs.tasks import _council_constraints, launch_block
from ppc_agent_server.models import ProposedChange
from ppc_agent_server.services.council import CouncilReply
from ppc_agent_server.services.council_guard import (
    CouncilBlock,
    blocked_message,
    council_context,
)

#: Cheia avizului in ``ProposedChange.before``.
REVIEW_KEY = "council_review"

#: ``(session, client_account_id, intrebare) -> raspunsul consiliului``.
Council = Callable[[Session, int, str], CouncilReply]


def launch_question(campaign_name: str, daily_budget: object) -> str:
    return (
        f"Lansăm o campanie Meta nouă, «{campaign_name}», cu un buget de {daily_budget} RON "
        "pe zi. Merită acum? Ce riscuri vedeți?"
    )


def review(reply: CouncilReply) -> dict[str, Any]:
    """Avizul, cat sa-l citeasca omul care aproba (si un audit, mai tarziu)."""
    ruling = reply.ruling
    return {
        "question_topic": reply.topic,
        "decision": ruling.decision,
        "financial_status": ruling.financial_status,
        "veto": ruling.veto,
        "cut": ruling.cut,
        "approved": ruling.approved,
        "reopen_when": ruling.reopen_when,
        "opinions": [
            {"member": opinion.member, "title": opinion.title, "opinion": opinion.opinion}
            for opinion in reply.opinions
        ],
        "reply": reply.reply,
        "consulted_at": reply.generated_at.isoformat(),
    }


def growth_block(session: Session, client_account_id: int) -> CouncilBlock | None:
    """Restrictia de acum care opreste o lansare (``tasks.launch_block``): veto-ul
    Tehnicianului sau CFO-ul pe un cont care pierde bani dovedit."""
    constraints = _council_constraints(session, client_account_id)
    return launch_block(session, client_account_id, constraints)


def blocked_by(block: CouncilBlock) -> dict[str, Any]:
    return {"message": blocked_message(block), "context": council_context(block)}


def require_council_clearance(session: Session, proposal: ProposedChange) -> None:
    """La aprobarea unei lansari: avizul exista si nicio restrictie nu a aparut intre timp.

    Raises:
        HTTPException: 409 fara aviz (propunere de dinainte de regula) sau cu o
            restrictie activa a consiliului.
    """
    if REVIEW_KEY not in (proposal.before or {}):
        raise HTTPException(
            status_code=409,
            detail=(
                "lansarea n-a trecut prin consiliu (propunere veche) - propune-o din nou, "
                "ca să primească avizul consiliului"
            ),
        )
    block = growth_block(session, proposal.client_account_id)
    if block is not None:
        raise HTTPException(status_code=409, detail=blocked_message(block))
