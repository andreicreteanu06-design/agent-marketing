"""Structuri de date tipizate pentru raportul de client."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from ppc_agent.campaign_objective import CampaignObjective


class AdReportLine(BaseModel):
    """Performanta unui anunt, in forma de aratat unui client."""

    ad_id: str
    platform: str
    status: str
    spend: Decimal
    revenue: Decimal
    conversions: int
    roas: float


class DecisionNarrative(BaseModel):
    """O decizie de optimizare, in limbaj simplu - fara jargon tehnic."""

    when: datetime
    text: str
    status: str


class ClientReport(BaseModel):
    """Raportul complet al unui client: totaluri, performanta per anunt,
    decizii recente de optimizare si o nota despre capacitatea bugetului."""

    client_name: str
    objective: CampaignObjective
    generated_at: datetime
    daily_budget: Decimal
    total_spend: Decimal
    total_revenue: Decimal
    roas: float
    total_conversions: int
    ads: list[AdReportLine] = Field(default_factory=list)
    decisions: list[DecisionNarrative] = Field(default_factory=list)
    capacity_note: str | None = None
    excluded_negative_keywords: int = 0
