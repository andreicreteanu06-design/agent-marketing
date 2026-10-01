"""Orchestreaza ingestia unei conversii: calificare -> hash PII -> persistare ->
actualizarea starii anuntului pentru motorul de decizie.

Punctul de legatura cu ``ppc_agent`` (CLI): :func:`to_ad_performance_state`
converteste un rand ``AdPerformanceRecord`` intr-un
:class:`~ppc_agent.decision.fatigue_models.AdPerformanceState`, pe care
``ppc_agent.decision.fatigue_monitor.evaluate_ad`` il consuma NESCHIMBAT -
serverul nu duplica logica de Kill Switch/Pruning Switch, doar alimenteaza
motorul deja existent cu date live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from ppc_agent.decision.fatigue_models import AdPerformanceState
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdLifecycleStatus,
    AdPerformanceRecord,
    ClientAccount,
    ConversionEvent,
    ConversionEventType,
)
from ppc_agent_server.schemas import ConversionOutcome
from ppc_agent_server.tracking.models import StandardizedConversion, hash_pii
from ppc_agent_server.tracking.qualification import ConversionQualifier


def to_ad_performance_state(record: AdPerformanceRecord) -> AdPerformanceState:
    """Converteste un rand persistat in :class:`AdPerformanceState`.

    Podul propriu-zis catre motorul de decizie CLI - vezi docstring-ul
    modulului. Conversiile Decimal -> float sunt deliberate: schema
    ``AdPerformanceState`` (definita pentru cerinta monitorului de oboseala)
    foloseste ``float`` pentru toate campurile numerice, in timp ce randul din
    baza de date foloseste ``Decimal`` pentru campurile monetare (precizie
    exacta la stocare, ca restul modelelor din ``ppc_agent_server``).

    ``launch_time`` primeste explicit ``tzinfo=UTC`` daca lipseste: SQLite nu
    pastreaza fusul orar la stocare, deci un ``datetime`` scris ca UTC revine
    "naiv" la citire — ``evaluate_ad`` scade ``current_time`` (mereu cu fus)
    din el si ar ridica ``TypeError`` fara aceasta normalizare. Depistat abia
    la verificarea live (uvicorn + Postgres/SQLite real), nu de teste — vezi
    testul dedicat ``test_to_ad_performance_state_normalizes_naive_datetime``.
    """
    launch_time = record.launch_time
    if launch_time.tzinfo is None:
        launch_time = launch_time.replace(tzinfo=UTC)
    return AdPerformanceState(
        ad_id=record.ad_id,
        platform=record.platform.value,
        status=record.status.value,
        launch_time=launch_time,
        spend=float(record.spend),
        target_cpa=float(record.target_cpa),
        conversions=record.conversions,
        impressions=record.impressions,
        clicks=record.clicks,
        ctr=record.ctr,
        account_median_ctr=record.account_median_ctr,
        frequency_7d=record.frequency_7d,
        six_second_view_rate=record.six_second_view_rate,
        cpa_3d=float(record.cpa_3d),
        cpa_baseline_14d=float(record.cpa_baseline_14d),
        bad_days_last_5=record.bad_days_last_5,
        ctr_3d=record.ctr_3d,
        ctr_baseline_14d=record.ctr_baseline_14d,
        ctr_baseline_7d=record.ctr_baseline_7d,
        cpa_baseline_7d=float(record.cpa_baseline_7d),
        six_second_view_rate_baseline=record.six_second_view_rate_baseline,
        bad_days_last_3=record.bad_days_last_3,
    )


def _get_or_create_ad_record(
    session: Session, client_account: ClientAccount, conversion: StandardizedConversion
) -> AdPerformanceRecord | None:
    """Randul existent pentru ``conversion.ad_id``, sau unul nou daca se poate.

    Returneaza ``None`` cand nu exista nimic de actualizat: fara ``ad_id`` (o
    conversie neatribuita, ex. lead organic) nu stim CARUI anunt ii apartine;
    fara ``ad_platform`` (la prima aparitie a unui ``ad_id`` nou) nu putem crea
    un rand fara sa stim platforma (camp obligatoriu in AdPerformanceState).
    """
    if conversion.ad_id is None:
        return None
    existing = session.exec(
        select(AdPerformanceRecord).where(
            AdPerformanceRecord.client_account_id == client_account.id,
            AdPerformanceRecord.ad_id == conversion.ad_id,
        )
    ).first()
    if existing is not None:
        return existing
    if conversion.ad_platform is None:
        return None

    record = AdPerformanceRecord(
        client_account_id=client_account.id,
        ad_id=conversion.ad_id,
        platform=AdFatiguePlatform(conversion.ad_platform),
        status=AdLifecycleStatus.NEW,
        launch_time=datetime.now(tz=UTC),
        target_cpa=client_account.default_lead_value,
    )
    session.add(record)
    return record


def find_event(session: Session, client_account_id: int, event_id: str) -> ConversionEvent | None:
    """Conversia ``event_id`` a ACESTUI client - deduplicarea e per client, nu globala."""
    return session.exec(
        select(ConversionEvent).where(
            ConversionEvent.client_account_id == client_account_id,
            ConversionEvent.event_id == event_id,
        )
    ).first()


def record_conversion(
    session: Session, client_account: ClientAccount, conversion: StandardizedConversion
) -> ConversionOutcome:
    """Califica, hash-uieste PII-ul, persista si (daca se poate) actualizeaza
    starea anuntului pentru o conversie deja adusa la forma standard.

    Idempotent pe ``event_id``: o conversie deja vazuta (webhook retrimis) nu
    se re-numara — returneaza verdictul salvat prima data, ``deduplicated=True``.

    Args:
        session: Sesiunea DB activa.
        client_account: Contul client caruia ii apartine conversia (deja
            validat fata de agentia autentificata).
        conversion: Conversia normalizata (iesita dintr-un adaptor de sursa).

    Returns:
        Rezultatul ingestiei.
    """
    existing_event = find_event(session, client_account.id or 0, conversion.event_id)
    if existing_event is not None:
        return ConversionOutcome(
            event_id=conversion.event_id,
            qualified=existing_event.qualified,
            reason=existing_event.disqualification_reason,
            deduplicated=True,
        )

    qualifier = ConversionQualifier(
        default_lead_value=float(client_account.default_lead_value),
        objective=client_account.objective,
    )
    result = qualifier.qualify(conversion)
    qualified_conversion = result.conversion

    event = ConversionEvent(
        client_account_id=client_account.id,
        event_id=qualified_conversion.event_id,
        event_type=ConversionEventType(qualified_conversion.event_type),
        value=(
            Decimal(str(qualified_conversion.value))
            if qualified_conversion.value is not None
            else None
        ),
        currency=qualified_conversion.currency,
        email_sha256=hash_pii(qualified_conversion.customer_email),
        phone_sha256=hash_pii(qualified_conversion.customer_phone, is_phone=True),
        source_platform=qualified_conversion.source_platform,
        lead_status=qualified_conversion.lead_status,
        call_duration_seconds=qualified_conversion.call_duration_seconds,
        ad_id=qualified_conversion.ad_id,
        qualified=result.qualified,
        disqualification_reason=result.reason,
    )
    session.add(event)

    if result.qualified:
        record = _get_or_create_ad_record(session, client_account, qualified_conversion)
        if record is not None:
            record.conversions += 1
            if qualified_conversion.value is not None:
                record.revenue += Decimal(str(qualified_conversion.value))
            record.updated_at = datetime.now(tz=UTC)
            session.add(record)

    session.commit()
    return ConversionOutcome(
        event_id=qualified_conversion.event_id, qualified=result.qualified, reason=result.reason
    )
