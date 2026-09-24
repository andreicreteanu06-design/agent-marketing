"""Stratul RAW: ce s-a intamplat, exact cum raporteaza sursele.

Doua surse, amandoua aduse aici fara nicio agregare:

- **platformele de reclame, zi cu zi** - prin ``SupportsDailyPerformance``,
  implementat de furnizorii live Google Ads si Meta. Se aduc DOUA ferestre
  (saptamana raportata + cea dinainte), ca evolutia sa se poata calcula.
- **deciziile executate** - randurile ``ProposedChange``. Pachetul ``ppc_agent``
  nu importa niciodata serverul, deci randurile vin de la apelant, prin
  :class:`ChangeRecord`, iar aici doar se filtreaza si se normalizeaza.

O sursa care lipseste nu e o eroare: devine un "gol de date" care ajunge in
raport, ca un zero sa nu para o saptamana fara cheltuieli.

Zilele sunt in UTC, peste tot. Un cont de reclame configurat pe ora Romaniei
raporteaza pe zilele lui; diferenta de cateva ore la granita zilei e acceptata,
dar spusa.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import pandas as pd

from ppc_agent.decision.pipeline import SupportsDailyPerformance

logger = logging.getLogger("ppc_agent.services.reporting.extractors")

#: Coloanele stratului RAW - cele ale citirii zilnice, plus platforma.
RAW_COLUMNS = ["date", "platform", "arm_id", "name", "clicks", "conversions", "cost", "revenue"]

PLATFORM_LABELS = {"google_ads": "Google Ads", "meta_ads": "Meta Ads"}


@dataclass(frozen=True, slots=True)
class ReportWindow:
    """O fereastra de raportare: zile calendaristice UTC, ambele capete incluse."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"fereastra se termina ({self.end}) inainte sa inceapa ({self.start})")

    @classmethod
    def ending(cls, end: date, days: int = 7) -> ReportWindow:
        """Cele ``days`` zile care se termina la ``end`` inclusiv."""
        return cls(start=end - timedelta(days=days - 1), end=end)

    @classmethod
    def last_complete_week(cls, today: date) -> ReportWindow:
        """Cele 7 zile care se termina ieri: ziua de azi nu s-a incheiat.

        Rulat lunea, e exact saptamana calendaristica trecuta.
        """
        return cls.ending(today - timedelta(days=1))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> ReportWindow:
        """Fereastra de aceeasi lungime, imediat dinainte - baza de comparatie."""
        return ReportWindow.ending(self.start - timedelta(days=1), self.days)

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.days)]

    def contains(self, moment: datetime) -> bool:
        """Adevarat daca ``moment`` cade intr-o zi din fereastra.

        Un ``datetime`` fara fus orar e tratat ca UTC - asa il intoarce SQLite.
        """
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return self.start <= aware.astimezone(UTC).date() <= self.end


class ReportSources(Protocol):
    """De unde vin zilele. ``ProviderFactory`` il satisface ca atare."""

    def google_ads(self) -> object: ...
    def meta(self) -> object: ...


@dataclass(slots=True)
class PlatformExtract:
    """Zilele aduse de la platforme, plus ce n-a putut fi adus si de ce."""

    frame: pd.DataFrame
    gaps: list[str] = field(default_factory=list)
    #: Platformele care AU raspuns - chiar si cu zero randuri (nicio livrare).
    platforms: list[str] = field(default_factory=list)


def extract_platform_daily(
    sources: ReportSources, *, accounts: dict[str, str], window: ReportWindow
) -> PlatformExtract:
    """Zilele saptamanii raportate si ale celei dinainte, de la fiecare platforma.

    Args:
        sources: Furnizorii - in productie, ``ProviderFactory``.
        accounts: Contul fiecarei platforme (``google_ads``, ``meta_ads``).
        window: Saptamana raportata.

    Returns:
        Randurile brute (:data:`RAW_COLUMNS`) si golurile de date. Nu ridica
        exceptii pentru o platforma stricata - ea apare in ``gaps``.
    """
    span = ReportWindow(start=window.previous.start, end=window.end)
    getters = {"google_ads": sources.google_ads, "meta_ads": sources.meta}
    frames: list[pd.DataFrame] = []
    gaps: list[str] = []
    platforms: list[str] = []

    for platform, getter in getters.items():
        label = PLATFORM_LABELS[platform]
        provider = getter()
        if not isinstance(provider, SupportsDailyPerformance):
            gaps.append(
                f"{label}: furnizorul activ nu raporteaza zi cu zi (in modul mock nu se "
                "fabrica serii zilnice dintr-un agregat)"
            )
            continue
        account_id = accounts.get(platform, "")
        if not account_id:
            gaps.append(f"{label}: contul nu e configurat pentru acest client")
            continue
        try:
            frame = provider.daily_campaign_performance(
                account_id, days=span.days, end_date=span.end
            )
        except Exception as exc:
            logger.warning("citire zilnica esuata pe %s: %s: %s", label, type(exc).__name__, exc)
            gaps.append(f"{label}: datele nu au putut fi citite ({type(exc).__name__}: {exc})")
            continue
        frames.append(frame.assign(platform=platform).reindex(columns=RAW_COLUMNS))
        platforms.append(platform)

    # O platforma fara livrare a raspuns (e in ``platforms``), dar tabelul ei gol
    # nu intra in concatenare: pandas isi va schimba regula de tipuri pentru
    # tabelele goale, iar rezultatul nu trebuie sa depinda de asta.
    non_empty = [frame for frame in frames if not frame.empty]
    frame = (
        pd.concat(non_empty, ignore_index=True)
        if non_empty
        else pd.DataFrame(columns=RAW_COLUMNS)
    )
    return PlatformExtract(frame=frame, gaps=gaps, platforms=platforms)


class ChangeRecord(Protocol):
    """Ce ii trebuie extractorului dintr-un rand ``ProposedChange``."""

    @property
    def op(self) -> str: ...
    @property
    def resource(self) -> str: ...
    @property
    def rationale(self) -> str: ...
    @property
    def source_module(self) -> str: ...
    @property
    def projected_daily_spend(self) -> Decimal: ...
    @property
    def decided_at(self) -> datetime | None: ...
    @property
    def decided_by(self) -> str | None: ...
    @property
    def execution_result(self) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """O decizie executata, normalizata pentru raport."""

    decided_at: datetime
    op: str
    resource: str
    rationale: str
    source_module: str
    projected_daily_spend: Decimal
    decided_by: str | None
    #: ``False`` cand executia a fost doar marcata, fara nicio schimbare pe platforma.
    applied: bool


def extract_decisions(
    changes: Iterable[ChangeRecord], window: ReportWindow
) -> list[DecisionRecord]:
    """Deciziile executate in fereastra, in ordine cronologica.

    Apelantul aduce doar randurile cu status ``executed``; aici se pastreaza cele
    decise in fereastra si se marcheaza cele simulate. Endpoint-ul agentiei
    ``POST /api/v1/proposals/{id}/execute`` marcheaza o propunere executata fara
    sa atinga vreo platforma - un raport pentru client nu are voie sa o prezinte
    ca aplicata.
    """
    records: list[DecisionRecord] = []
    for change in changes:
        if change.decided_at is None or not window.contains(change.decided_at):
            continue
        moment = change.decided_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        simulated = bool((change.execution_result or {}).get("simulated"))
        records.append(
            DecisionRecord(
                decided_at=moment,
                op=str(change.op),
                resource=change.resource,
                rationale=change.rationale,
                source_module=change.source_module,
                projected_daily_spend=change.projected_daily_spend,
                decided_by=change.decided_by,
                applied=not simulated,
            )
        )
    return sorted(records, key=lambda record: record.decided_at)
