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

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, func, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.decision.fatigue_models import AdPerformanceState
from ppc_agent.providers.live.meta import AdDay, AdInsight
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
        conversions=record.counted[0],
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


#: Ferestrele portii C pentru Meta (``fatigue_monitor``): CTR/CPA pe ultimele 3 zile
#: fata de ultimele 14, si zilele proaste din ultimele 5.
_RECENT_DAYS = 3
_BASELINE_DAYS = 14
_BAD_DAYS_WINDOW = 5
_CENT = Decimal("0.01")


def _totals(days: list[AdDay]) -> tuple[float, int, int, float]:
    """(cheltuiala, afisari, click-uri, conversii) pe zilele date."""
    return (
        sum(day.spend for day in days),
        sum(day.impressions for day in days),
        sum(day.clicks for day in days),
        sum(day.conversions for day in days),
    )


def _cpa(spend: float, conversions: float) -> float:
    """CPA-ul unei ferestre; fara conversii, cel putin cheltuiala ei (nu infinit)."""
    return spend / conversions if conversions > 0 else spend


def _ctr(clicks: int, impressions: int) -> float:
    return clicks / impressions if impressions else 0.0


def apply_platform_insight(
    record: AdPerformanceRecord,
    insight: AdInsight,
    *,
    target_cpa: Decimal,
    account_median_ctr: float,
    now: datetime | None = None,
) -> None:
    """Scrie in ``record`` ce a citit agentul din Meta, pentru monitorul de oboseala.

    Nu atinge ``conversions``/``revenue`` (ale webhook-ului). Starea se recalculeaza in
    fiecare noapte: ``paused`` cand anuntul nu ruleaza; ``profitable`` cand are vanzari
    la un CPA de cel mult tinta - atunci poarta C il judeca pe oboseala; altfel ``new``
    - poarta B: cheltuiala fara vanzari. O zi proasta: a cheltuit, iar CPA-ul ei (sau
    cheltuiala, fara vanzari) e peste tinta.
    """
    now = now or datetime.now(tz=UTC)
    record.target_cpa = target_cpa
    record.launch_time = insight.created_time.astimezone(UTC)
    record.updated_at = now
    if not insight.active:
        record.status = AdLifecycleStatus.PAUSED
        return
    record.spend = Decimal(str(insight.spend)).quantize(_CENT)
    record.impressions = insight.impressions
    record.clicks = insight.clicks
    record.ctr = _ctr(insight.clicks, insight.impressions)
    record.account_median_ctr = account_median_ctr
    record.frequency_7d = insight.frequency_7d
    record.video_views = insight.video_views
    record.platform_conversions = round(insight.conversions)
    record.platform_revenue = Decimal(str(insight.revenue)).quantize(_CENT)

    yesterday = now.date() - timedelta(days=1)

    def last(days: int) -> list[AdDay]:
        return [day for day in insight.days if 0 <= (yesterday - day.day).days < days]

    spend_3d, impressions_3d, clicks_3d, conversions_3d = _totals(last(_RECENT_DAYS))
    spend_14d, impressions_14d, clicks_14d, conversions_14d = _totals(last(_BASELINE_DAYS))
    record.ctr_3d = _ctr(clicks_3d, impressions_3d)
    record.ctr_baseline_14d = _ctr(clicks_14d, impressions_14d)
    record.cpa_3d = Decimal(str(_cpa(spend_3d, conversions_3d))).quantize(_CENT)
    record.cpa_baseline_14d = Decimal(str(_cpa(spend_14d, conversions_14d))).quantize(_CENT)
    record.bad_days_last_5 = sum(
        1
        for day in last(_BAD_DAYS_WINDOW)
        if day.spend > 0 and _cpa(day.spend, day.conversions) > float(target_cpa)
    )

    conversions, _ = record.counted
    profitable = conversions > 0 and record.spend / conversions <= target_cpa
    record.status = AdLifecycleStatus.PROFITABLE if profitable else AdLifecycleStatus.NEW


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
        target_cpa=client_account.target_cpa(),
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
    Exceptie: un ``lead_status`` nou (vanzarile au calificat lead-ul in CRM) reface
    verdictul - vezi :func:`_requalify`.

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
        status = (conversion.lead_status or "").strip().lower()
        if status and status != (existing_event.lead_status or "").strip().lower():
            return _requalify(session, client_account, existing_event, conversion)
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

    # Randul anuntului se creeaza la prima aparitie, chiar si pentru un lead in asteptare:
    # CRM-ul care il califica mai tarziu trimite doar statusul, fara platforma.
    record = _get_or_create_ad_record(session, client_account, qualified_conversion)
    if result.qualified and record is not None:
        record.conversions += 1
        if qualified_conversion.value is not None:
            record.revenue += Decimal(str(qualified_conversion.value))
        record.updated_at = datetime.now(tz=UTC)
        session.add(record)

    session.commit()
    return ConversionOutcome(
        event_id=qualified_conversion.event_id, qualified=result.qualified, reason=result.reason
    )


def _requalify(
    session: Session,
    client_account: ClientAccount,
    event: ConversionEvent,
    conversion: StandardizedConversion,
) -> ConversionOutcome:
    """Statusul unui lead deja primit s-a schimbat (CRM): verdictul si contoarele se refac.

    CRM-ul poate trimite doar ``event_id`` si statusul: tipul, valoarea si durata
    apelului raman cele salvate la prima primire.
    """
    qualifier = ConversionQualifier(
        default_lead_value=float(client_account.default_lead_value),
        objective=client_account.objective,
    )
    result = qualifier.qualify(
        conversion.model_copy(
            update={
                "event_type": event.event_type.value,
                "value": float(event.value) if event.value is not None else conversion.value,
                "call_duration_seconds": (
                    conversion.call_duration_seconds or event.call_duration_seconds
                ),
            }
        )
    )
    changed = result.qualified != event.qualified
    event.lead_status = conversion.lead_status
    event.qualified = result.qualified
    event.disqualification_reason = result.reason
    session.add(event)
    if changed and event.ad_id is not None:
        # Calificat acum: randul anuntului se poate crea (un lead in asteptare nu l-a creat);
        # descalificat: doar unul existent se corecteaza.
        lookup = conversion.model_copy(
            update={
                "ad_id": event.ad_id,
                "ad_platform": conversion.ad_platform if result.qualified else None,
            }
        )
        record = _get_or_create_ad_record(session, client_account, lookup)
        if record is not None:
            step = 1 if result.qualified else -1
            record.conversions = max(0, record.conversions + step)
            if event.value is not None:
                record.revenue = max(Decimal("0"), record.revenue + step * event.value)
            record.updated_at = datetime.now(tz=UTC)
            session.add(record)
    session.commit()
    return ConversionOutcome(
        event_id=event.event_id,
        qualified=result.qualified,
        reason=result.reason,
        deduplicated=True,
        requalified=True,
    )


#: Fereastra platformelor (ultimele 30 de zile), ca venitul magazinului sa fie comparabil.
SHOP_WINDOW_DAYS = 30


def shop_revenue(
    session: Session,
    account: ClientAccount,
    *,
    days: int = SHOP_WINDOW_DAYS,
    now: datetime | None = None,
) -> Decimal | None:
    """Valoarea conversiilor calificate primite de la client in ultimele ``days`` zile.

    E venitul real, numarat o singura data - spre deosebire de suma platformelor, unde
    fiecare isi atribuie vanzarile ei. La un magazin, doar comenzile; la lead-uri, toate
    conversiile calificate (cu valoarea lor proxy). Include si vanzarile organice, deci
    e un plafon, nu venitul reclamelor.

    ``None`` cand webhook-ul nu acopera toata fereastra (prima conversie e mai noua decat
    inceputul ei): o suma partiala ar parea o prabusire a vanzarilor si ar taia bugetul.
    """
    start = (now or datetime.now(tz=UTC)) - timedelta(days=days)
    conditions = [ConversionEvent.client_account_id == account.id]
    if account.objective is CampaignObjective.SALES:
        conditions.append(ConversionEvent.event_type == ConversionEventType.PURCHASE)
    first = session.exec(select(func.min(ConversionEvent.created_at)).where(*conditions)).one()
    # SQLite pierde fusul orar la stocare: un ``created_at`` scris in UTC revine naiv.
    if first is None or (first if first.tzinfo else first.replace(tzinfo=UTC)) > start:
        return None
    total = session.exec(
        select(func.sum(ConversionEvent.value)).where(
            *conditions,
            col(ConversionEvent.qualified).is_(True),
            ConversionEvent.created_at >= start,
        )
    ).one()
    return Decimal(str(total or 0)).quantize(Decimal("0.01"))
