"""Stratul SERVING: JSON-ul pe care il consuma frontend-ul, gata de grafice.

Forma e gandita pentru Recharts/Tremor: liste de obiecte cu chei stabile, cate un
obiect pe punct de grafic, numere ca numere, si ``null`` unde valoarea nu exista.
Recharts lasa un gol la ``null`` (sau il uneste, cu ``connectNulls``) - nu
deseneaza un zero care minte. Un grafic se leaga direct::

    <LineChart data={report.daily_performance_chart}>
      <Line dataKey="cpa" />
    </LineChart>

``kpis`` poarta si ``better_when``: CPA-ul care scade e o veste buna, cheltuiala
care creste nu e nici buna, nici rea - frontend-ul coloreaza evolutia dupa el,
fara sa aiba propria lista de reguli.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from ppc_agent.services.reporting.extractors import (
    PLATFORM_LABELS,
    DecisionRecord,
    PlatformExtract,
    ReportWindow,
)
from ppc_agent.services.reporting.summary import (
    ReportSummarizer,
    SummarySource,
    build_facts,
    executive_summary,
    template_summary,
)
from ppc_agent.services.reporting.transformers import (
    KpiKey,
    PeriodTotals,
    daily_series,
    normalize,
    platform_totals,
    totals,
    week_over_week,
)

REPORT_VERSION: Literal[1] = 1

_KPI_META: dict[KpiKey, tuple[str, Literal["higher", "lower", "neutral"]]] = {
    "spend": ("Cheltuiala", "neutral"),
    "conversions": ("Conversii", "higher"),
    "cpa": ("CPA", "lower"),
    "roas": ("ROAS", "higher"),
    "revenue": ("Venit", "higher"),
    "clicks": ("Click-uri", "higher"),
}

_SOURCE_LABELS = {
    "autonomous_evaluator": "evaluatorul autonom",
    "campaign_launch": "lansare de campanie",
    "budget": "planul de buget (Kelly + Thompson)",
    "negatives": "cuvinte cheie negative",
    "meta_liquidity": "consolidare de lichiditate Meta",
}


class ReportPeriod(BaseModel):
    start: dt.date
    end: dt.date


class DailyPerformancePoint(BaseModel):
    """Un punct de grafic: o zi, toate platformele insumate."""

    date: dt.date
    spend: float
    clicks: int
    conversions: float
    revenue: float | None
    cpa: float | None
    roas: float | None


class KpiCard(BaseModel):
    """Un indicator al saptamanii, cu evolutia fata de cea anterioara."""

    key: KpiKey
    label: str
    current: float | None
    previous: float | None
    change_pct: float | None
    better_when: Literal["higher", "lower", "neutral"]


class PlatformRow(BaseModel):
    """Totalurile saptamanii pe o platforma - pentru un grafic cu bare sau un tabel."""

    platform: str
    label: str
    spend: float
    clicks: int
    conversions: float
    revenue: float | None
    cpa: float | None
    roas: float | None


class DecisionLogEntry(BaseModel):
    """O decizie executata in saptamana raportata."""

    decided_at: dt.datetime
    action: str
    description: str
    resource: str
    rationale: str
    source: str
    approved_by: str | None
    projected_daily_spend: float
    #: ``False`` cand decizia a fost doar marcata ca executata, fara aplicare
    #: pe platforma - frontend-ul o arata separat, nu ca pe o schimbare reala.
    applied: bool


class WeeklyReportPayload(BaseModel):
    """Raportul saptamanal, exact cum il primeste frontend-ul."""

    report_version: Literal[1] = REPORT_VERSION
    client_account_id: int
    currency: str
    period: ReportPeriod
    previous_period: ReportPeriod
    generated_at: dt.datetime
    executive_summary: str
    #: ``"ai"`` doar cand textul modelului a trecut verificarea cifrelor.
    summary_source: SummarySource
    kpis: list[KpiCard] = Field(default_factory=list)
    daily_performance_chart: list[DailyPerformancePoint] = Field(default_factory=list)
    platform_breakdown: list[PlatformRow] = Field(default_factory=list)
    ai_decisions_log: list[DecisionLogEntry] = Field(default_factory=list)
    #: Ce lipseste din raport si de ce - un zero fara explicatie ar parea o
    #: saptamana fara cheltuieli.
    data_gaps: list[str] = Field(default_factory=list)


def _describe(record: DecisionRecord, currency: str) -> str:
    if record.op == "PAUSE":
        return f"Pauza pe {record.resource}"
    if record.op == "UPDATE":
        return f"Buget zilnic {record.projected_daily_spend} {currency} pe {record.resource}"
    if record.op == "CREATE_CAMPAIGN":
        return f"Campanie noua lansata, oprita, in {record.resource}"
    if record.op == "CREATE":
        return f"Adaugat {record.resource}"
    return f"{record.op} pe {record.resource}"


def _source_label(source_module: str) -> str:
    if source_module.startswith("mcp:"):
        return "agentul AI (MCP)"
    return _SOURCE_LABELS.get(source_module, source_module)


def _point(day: dt.date, values: PeriodTotals) -> DailyPerformancePoint:
    return DailyPerformancePoint(
        date=day,
        spend=values.spend,
        clicks=values.clicks,
        conversions=round(values.conversions, 2),
        revenue=values.revenue if values.track_roas else None,
        cpa=values.cpa,
        roas=values.roas,
    )


def build_weekly_report(
    *,
    client_account_id: int,
    currency: str,
    window: ReportWindow,
    extract: PlatformExtract,
    decisions: list[DecisionRecord],
    summarizer: ReportSummarizer | None,
    track_roas: bool,
    generated_at: dt.datetime | None = None,
) -> WeeklyReportPayload:
    """Leaga cele trei straturi intr-un raport.

    Args:
        extract: Stratul RAW de la platforme (:func:`extract_platform_daily`).
        decisions: Deciziile executate (:func:`extract_decisions`).
        summarizer: Modelul care scrie rezumatul; ``None`` = rezumatul din cifre.
        track_roas: ``False`` la obiectivul de lead-uri - ROAS si venitul devin
            ``null``, nu zero.
    """
    frame = normalize(extract.frame)
    has_data = bool(extract.platforms)
    current = totals(frame, window, track_roas=track_roas)
    previous = totals(frame, window.previous, track_roas=track_roas)
    changes = week_over_week(current, previous)
    gaps = list(extract.gaps)

    facts = build_facts(
        window=window,
        currency=currency,
        current=current,
        previous=previous,
        changes=changes,
        decisions=decisions,
        gaps=gaps,
        has_data=has_data,
    )
    template = template_summary(
        window=window,
        currency=currency,
        current=current,
        previous=previous,
        decisions=decisions,
        gaps=gaps,
        has_data=has_data,
    )
    summary, source, note = executive_summary(summarizer, facts, template)
    if note:
        gaps.append(note)

    return WeeklyReportPayload(
        client_account_id=client_account_id,
        currency=currency,
        period=ReportPeriod(start=window.start, end=window.end),
        previous_period=ReportPeriod(start=window.previous.start, end=window.previous.end),
        generated_at=generated_at or dt.datetime.now(tz=dt.UTC),
        executive_summary=summary,
        summary_source=source,
        kpis=(
            [
                KpiCard(
                    key=change.key,
                    label=_KPI_META[change.key][0],
                    current=change.current,
                    previous=change.previous,
                    change_pct=change.change_pct,
                    better_when=_KPI_META[change.key][1],
                )
                for change in changes
            ]
            if has_data
            else []
        ),
        daily_performance_chart=(
            [
                _point(day, values)
                for day, values in daily_series(frame, window, track_roas=track_roas)
            ]
            if has_data
            else []
        ),
        platform_breakdown=[
            PlatformRow(
                platform=platform,
                label=PLATFORM_LABELS.get(platform, platform),
                spend=values.spend,
                clicks=values.clicks,
                conversions=round(values.conversions, 2),
                revenue=values.revenue if track_roas else None,
                cpa=values.cpa,
                roas=values.roas,
            )
            for platform, values in platform_totals(
                frame, window, extract.platforms, track_roas=track_roas
            )
        ],
        ai_decisions_log=[
            DecisionLogEntry(
                decided_at=record.decided_at,
                action=record.op,
                description=_describe(record, currency),
                resource=record.resource,
                rationale=record.rationale,
                source=_source_label(record.source_module),
                approved_by=record.decided_by,
                projected_daily_spend=float(record.projected_daily_spend),
                applied=record.applied,
            )
            for record in decisions
        ],
        data_gaps=gaps,
    )
