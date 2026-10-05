"""Memoria CCO-ului in baza de date: contextul de dinaintea evaluarii si lectiile de dupa.

- :func:`build_context` aduna ce stiu ceilalti agenti: avatarul JTBD (interviul), ipoteza
  CMO-ului (publicata de directiva de noapte; fara ea, calculata din interviu), lectiile
  contului (``performancecalibration``, ultimele 90 de zile) si trendurile din trends_db.
- :func:`save_evaluation` pastreaza verdictul, ca PPC-ul sa-i poata raspunde.
- :func:`record_feedback` primeste raspunsul PPC-ului (``PerformanceFeedback``) si scrie
  corectiile - o lectie pe (evaluare, anunt, metrica), actualizata, nu dublata.
- :func:`launch_feedback` e partea PPC-ului: din lansarile executate si cifrele de noapte
  ale anunturilor (``AdPerformanceRecord``), payload-urile pentru CCO.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from ppc_agent.texttools import tokenize
from ppc_agent_server.models import (
    AdPerformanceRecord,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    CreativeEvaluationRecord,
    CreativeTrend,
    PerformanceCalibration,
    ProposedChange,
)
from ppc_agent_server.services.avatar_builder import (
    avatar_from_answers,
    avatar_texts,
    offer_from_answers,
)
from ppc_agent_server.services.creative_context import (
    CALIBRATION_WINDOW_DAYS,
    AdPlatform,
    CalibrationLesson,
    CreativeEvaluationContext,
    PerformanceFeedback,
    PerformanceMetrics,
    Purpose,
    TrendInsight,
    calibrate,
)
from ppc_agent_server.services.propensity import Experiment, design_experiment, score_propensity

#: Cate note din trends_db ajung in prompt.
MAX_TRENDS = 3
#: Cuvintele prea scurte nu spun nimic despre industrie ("de", "si", "auto" ramane).
_MIN_TERM = 4
#: Cheia verdictului CCO-ului in ``before`` (aceeasi ca ``routers/campaigns.CREATIVE_KEY``).
CREATIVE_KEY = "creative_review"


class FeedbackError(ValueError):
    """Un feedback care nu se poate lega de o evaluare a acestui client."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


def cmo_hypothesis(account: ClientAccount) -> Experiment | None:
    """Ipoteza CMO-ului: cea publicata noaptea; altfel, din ce a spus clientul in interviu."""
    if account.cmo_hypothesis:
        return Experiment.model_validate(account.cmo_hypothesis)
    avatar = avatar_from_answers(account.avatar_answers)
    score = score_propensity(
        avatar=avatar,
        offer=offer_from_answers(account.avatar_answers),
        measured_barrier=None,
        alignment=[],
    )
    return design_experiment(score, avatar)


def account_lessons(
    session: Session, client_account_id: int, *, now: datetime | None = None
) -> list[CalibrationLesson]:
    """Ce a gresit CCO-ul pe acest cont, dupa cifrele din piata (cele mai noi intai)."""
    since = (now or _now()) - timedelta(days=CALIBRATION_WINDOW_DAYS)
    rows = session.exec(
        select(PerformanceCalibration)
        .where(PerformanceCalibration.client_account_id == client_account_id)
        .where(PerformanceCalibration.created_at >= since)
        .order_by(col(PerformanceCalibration.created_at).desc())
    ).all()
    return [CalibrationLesson.model_validate(row, from_attributes=True) for row in rows]


def _terms(texts: Iterable[str]) -> set[str]:
    return {token for text in texts for token in tokenize(text) if len(token) >= _MIN_TERM}


def industry_terms(account: ClientAccount) -> set[str]:
    """Cuvintele care spun in ce industrie e clientul: numele, tipul afacerii, treaba JTBD."""
    avatar = avatar_from_answers(account.avatar_answers)
    return _terms([account.name, account.brand_name, account.business_kind, *avatar_texts(avatar)])


def retrieve_trends(
    session: Session,
    tenant_id: int,
    terms: set[str],
    *,
    platform: AdPlatform | None,
    today: date,
    limit: int = MAX_TRENDS,
) -> list[TrendInsight]:
    """Notele din trends_db care se potrivesc industriei (RAG pe cuvinte, fara embeddings).

    Doar cele neexpirate, de pe platforma creativei sau pentru toate. O nota cu industria
    goala e generala: intra dupa cele potrivite. Ordinea: cate cuvinte au in comun, apoi
    cele mai noi.
    """
    rows = session.exec(
        select(CreativeTrend)
        .where(CreativeTrend.tenant_id == tenant_id)
        .where(CreativeTrend.expires_at >= today)
    ).all()
    scored: list[tuple[int, date, CreativeTrend]] = []
    for row in rows:
        if platform is not None and row.platform not in (platform, "all"):
            continue
        overlap = len(_terms([row.industry]) & terms)
        if row.industry.strip() and not overlap:
            continue  # alta industrie
        scored.append((overlap, row.observed_at, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        TrendInsight.model_validate(row, from_attributes=True) for _, _, row in scored[:limit]
    ]


def build_context(
    session: Session,
    account: ClientAccount,
    *,
    purpose: Purpose = "ad",
    platform: AdPlatform | None = None,
    alt_text: str | None = None,
    now: datetime | None = None,
) -> CreativeEvaluationContext:
    """Tot ce trebuie sa stie CCO-ul de la ceilalti agenti inainte de evaluare."""
    moment = now or _now()
    return CreativeEvaluationContext(
        purpose=purpose,
        platform=platform,
        avatar=avatar_from_answers(account.avatar_answers),
        cmo_hypothesis=cmo_hypothesis(account) if purpose == "ad" else None,
        lessons=account_lessons(session, account.id or 0, now=moment),
        trends=retrieve_trends(
            session,
            account.tenant_id,
            industry_terms(account),
            platform=platform,
            today=moment.date(),
        )
        if purpose == "ad"
        else [],
        alt_text=alt_text,
    )


def save_evaluation(
    session: Session,
    client_account_id: int,
    asset_sha256: str,
    result: dict[str, Any],
    context: CreativeEvaluationContext,
) -> int:
    """Pastreaza verdictul CCO-ului; intoarce id-ul pe care PPC-ul il va cita in feedback."""
    record = CreativeEvaluationRecord(
        client_account_id=client_account_id,
        asset_sha256=asset_sha256,
        asset_type=str(result["asset_type"]),
        purpose=context.purpose,
        platform=context.platform or "",
        decision=str(result["decision"]),
        scores=dict(result["scores"]),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    assert record.id is not None
    return record.id


def link_ad(
    session: Session, record: CreativeEvaluationRecord, *, platform: AdPlatform, ad_id: str
) -> None:
    """Leaga verdictul de anuntul in care a ajuns creativa (lansata si din Ads Manager)."""
    record.ad_platform = platform
    record.ad_id = ad_id
    session.add(record)
    session.commit()


def record_feedback(
    session: Session, client_account_id: int, feedback: PerformanceFeedback
) -> list[CalibrationLesson]:
    """Raspunsul PPC-ului: corectiile pe care le scrie, pentru evaluarile acestui client.

    Raises:
        FeedbackError: evaluarea nu exista sau e a altui client.
    """
    record = session.get(CreativeEvaluationRecord, feedback.evaluation_id)
    if record is None or record.client_account_id != client_account_id:
        raise FeedbackError("evaluarea CCO nu există pentru acest client")
    if not record.ad_id:
        link_ad(session, record, platform=feedback.platform, ad_id=feedback.ad_id)
    lessons = calibrate(record.scores, record.asset_type, feedback)
    for lesson in lessons:
        row = session.exec(
            select(PerformanceCalibration)
            .where(PerformanceCalibration.evaluation_id == feedback.evaluation_id)
            .where(PerformanceCalibration.ad_id == feedback.ad_id)
            .where(PerformanceCalibration.metric == lesson.metric)
        ).first() or PerformanceCalibration(
            client_account_id=client_account_id,
            evaluation_id=feedback.evaluation_id,
            platform=feedback.platform,
            ad_id=feedback.ad_id,
            **lesson.model_dump(),
        )
        for field, value in lesson.model_dump().items():
            setattr(row, field, value)
        row.created_at = _now()
        session.add(row)
    session.commit()
    return lessons


def _launched(session: Session, client_account_id: int) -> dict[int, str]:
    """Evaluarea CCO -> anuntul Meta, din lansarile executate de platforma."""
    launches = session.exec(
        select(ProposedChange)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.op == ChangeOp.CREATE_CAMPAIGN)
        .where(ProposedChange.status == ChangeStatus.EXECUTED)
    ).all()
    linked: dict[int, str] = {}
    for launch in launches:
        review = launch.before.get(CREATIVE_KEY) or {}
        evaluation_id = review.get("evaluation_id") if isinstance(review, dict) else None
        ad_id = str((launch.execution_result or {}).get("ad_id", "")).strip()
        if isinstance(evaluation_id, int) and ad_id:
            linked[evaluation_id] = ad_id
    return linked


def launch_feedback(
    session: Session, account: ClientAccount, *, now: datetime | None = None
) -> list[PerformanceFeedback]:
    """Partea PPC-ului: cifrele de noapte ale anunturilor in care au ajuns creative judecate.

    Doar Meta, deocamdata (acolo ruleaza sincronizarea de noapte a anunturilor).
    """
    client_id = account.id or 0
    records = session.exec(
        select(CreativeEvaluationRecord).where(
            CreativeEvaluationRecord.client_account_id == client_id
        )
    ).all()
    launched = _launched(session, client_id)
    performance = {
        row.ad_id: row
        for row in session.exec(
            select(AdPerformanceRecord).where(AdPerformanceRecord.client_account_id == client_id)
        ).all()
    }
    moment = now or _now()
    out: list[PerformanceFeedback] = []
    for record in records:
        ad_id = record.ad_id or launched.get(record.id or 0, "")
        if record.ad_platform not in ("", "meta") or not ad_id or ad_id not in performance:
            continue
        ad = performance[ad_id]
        conversions, revenue = ad.counted
        launched_at = ad.launch_time if ad.launch_time.tzinfo else ad.launch_time.replace(
            tzinfo=UTC
        )
        out.append(
            PerformanceFeedback(
                evaluation_id=record.id or 0,
                platform="meta",
                ad_id=ad_id,
                window_days=max(1, min(365, (moment - launched_at).days or 1)),
                metrics=PerformanceMetrics(
                    impressions=ad.impressions,
                    clicks=ad.clicks,
                    video_views_3s=ad.video_views if record.asset_type == "video" else None,
                    spend=ad.spend,
                    revenue=revenue,
                    conversions=conversions,
                ),
                break_even_roas=float(account.break_even_roas),
            )
        )
    return out
