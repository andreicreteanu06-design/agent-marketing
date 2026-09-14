"""Incarca baza de cunostinte de marketing (principii de persuasiune consacrate),
filtrate dupa :class:`~ppc_agent.campaign_objective.CampaignObjective`.

Continut curatat si scris original pentru acest proiect - inspirat de principii
CONSACRATE, generice (Cialdini, direct-response), nu reprodus din nicio sursa
externa. Provenienta cercetarii: catalogul de principii din
github.com/coreyhaines31/marketingskills (skill "marketing-psychology", MIT
- "Use these however you want") - folosit STRICT ca referinta pentru NUMELE
principiilor consacrate (Raritate, Autoritate, Dovada Sociala etc. - concepte
generice, decenii vechi, nu proprietatea acelui repo), nu ca text copiat sau
dependinta live la runtime.

Deviere deliberata de la "clonare live + citire markdown la runtime": textul
sursa e proza nestructurata a unei terte parti, a carei organizare poate
diverge oricand intre versiuni - un loader care parseaza acel text ar fi
fragil si neverificabil determinist, exact genul de dependinta pe care restul
proiectului il evita (mock-first, fara nimic nesigur la runtime). In loc de
asta, ``marketing_knowledge_base.json`` e comis in repo, curat si editabil
manual - la fel ca ``swipe_file.json`` (acelasi tipar: :func:`load_swipe_file`).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.errors import KnowledgeBaseError


class MarketingPrinciple(BaseModel):
    """Un principiu de psihologie/copywriting: numele consacrat + aplicarea lui."""

    name: str
    guidance: str


class MarketingKnowledgeBase(BaseModel):
    """Catalogul complet, impartit pe obiectiv de campanie."""

    sales_frameworks: list[MarketingPrinciple]
    lead_gen_frameworks: list[MarketingPrinciple]


def default_knowledge_base_path() -> Path:
    """Calea implicita catre ``marketing_knowledge_base.json`` (langa acest modul)."""
    return Path(__file__).resolve().parent / "marketing_knowledge_base.json"


def load_knowledge_base(path: Path | str | None = None) -> MarketingKnowledgeBase:
    """Incarca si valideaza baza de cunostinte de marketing.

    Args:
        path: Cale explicita. Daca lipseste, se foloseste
            :func:`default_knowledge_base_path`.

    Returns:
        Catalogul validat.

    Raises:
        KnowledgeBaseError: Fisierul lipseste, nu e JSON valid, sau nu respecta schema.
    """
    resolved = Path(path) if path is not None else default_knowledge_base_path()
    if not resolved.is_file():
        raise KnowledgeBaseError(f"baza de cunostinte nu a fost gasita la {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(f"baza de cunostinte nu e JSON valid: {exc}") from exc
    try:
        return MarketingKnowledgeBase.model_validate(raw)
    except ValidationError as exc:
        raise KnowledgeBaseError(f"baza de cunostinte nu respecta schema: {exc}") from exc


def frameworks_for_objective(
    knowledge_base: MarketingKnowledgeBase, objective: CampaignObjective
) -> list[MarketingPrinciple]:
    """Principiile relevante pentru un obiectiv de campanie."""
    if objective == CampaignObjective.SALES:
        return list(knowledge_base.sales_frameworks)
    return list(knowledge_base.lead_gen_frameworks)


def render_frameworks(principles: list[MarketingPrinciple]) -> str:
    """Formateaza principiile ca text compact, gata de injectat intr-un system prompt."""
    return "\n".join(f"- {principle.name}: {principle.guidance}" for principle in principles)
