"""Memoria CCO-ului in baza de date: contextul de dinaintea evaluarii si lectiile de dupa.

- :func:`build_context` aduna ce stiu ceilalti agenti: avatarul JTBD (interviul), ipoteza
  CMO-ului (publicata de directiva de noapte; fara ea, calculata din interviu), lectiile
  contului (``performancecalibration``, ultimele 90 de zile) si trendurile din trends_db.
- :func:`save_evaluation` pastreaza verdictul, ca PPC-ul sa-i poata raspunde.
- :func:`record_feedback` primeste raspunsul PPC-ului (``PerformanceFeedback``) si scrie
  corectiile - o lectie pe (evaluare, anunt, metrica), actualizata, nu dublata.
- :func:`launch_feedback` e partea PPC-ului: din lansarile executate si cifrele de noapte
  ale anunturilor (``AdPerformanceRecord``), payload-urile pentru CCO.
- :func:`ingest_trends` primeste trendurile automatizarii saptamanale, le da vectori
  (``embeddings.py``) si sterge ce e mai vechi de 30 de zile (:func:`purge_old_trends`).
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_
from sqlmodel import Session, col, select

from ppc_agent.errors import ProviderError
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
    TREND_TTL_DAYS,
    AdPlatform,
    CalibrationLesson,
    CreativeEvaluationContext,
    PerformanceFeedback,
    PerformanceMetrics,
    Purpose,
    TrendIngest,
    TrendIngestResult,
    TrendInsight,
    calibrate,
)
from ppc_agent_server.services.embeddings import (
    HASH_MODEL,
    Embedder,
    HashEmbedder,
    cosine,
    embed_or_fallback,
)
from ppc_agent_server.services.propensity import Experiment, design_experiment, score_propensity

#: Cate note din trends_db ajung in prompt.
MAX_TRENDS = 3
#: Cuvintele prea scurte nu spun nimic despre industrie ("de", "si", "auto" ramane).
_MIN_TERM = 4
#: Cheia verdictului CCO-ului in ``before`` (aceeasi ca ``routers/campaigns.CREATIVE_KEY``).
CREATIVE_KEY = "creative_review"
#: De la ce cosinus un trend e "din industria clientului", pe model. Vectorii lexicali au
#: cosinusuri mici intre texte de lungimi diferite; cei semantici, mari si intre straini.
# ponytail: praguri fixe pe model; calibreaza-le pe trendurile reale, daca devine important.
_MIN_SIMILARITY = {HASH_MODEL: 0.15}
_DEFAULT_MIN_SIMILARITY = 0.5


class FeedbackError(ValueError):
    """Un feedback care nu se poate lega de o evaluare a acestui client."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


def cmo_hypothesis(account: ClientAccount) -> Experiment | None:
    """Ipoteza CMO-ului: cea publicata noaptea; altfel, din ce a spus clientul in interviu."""
    if account.cmo_hypothesis:
        return Experiment.model_validate(account.cmo_hypothesis)
    avatar = avatar_from_answers(account.avatar_answers)
    offer = offer_from_answers(account.avatar_answers)
    score = score_propensity(avatar=avatar, offer=offer, measured_barrier=None, alignment=[])
    return design_experiment(score, avatar, offer)


def account_lessons(
    session: Session, client_account_id: int, *, now: datetime | None = None
) -> list[CalibrationLesson]:
    """Ce a gresit CCO-ul pe acest cont, dupa cifrele din piata (cele mai noi intai)."""
    since = (now or _now()) - timedelta(days=CALIBRATION_WINDOW_DAYS)
    rows = session.exec(
        select(PerformanceCalibration, CreativeEvaluationRecord)
        .join(
            CreativeEvaluationRecord,
            col(PerformanceCalibration.evaluation_id) == col(CreativeEvaluationRecord.id),
        )
        .where(PerformanceCalibration.client_account_id == client_account_id)
        .where(PerformanceCalibration.created_at >= since)
        .order_by(col(PerformanceCalibration.created_at).desc())
    ).all()
    # Fiecare lectie stie si ce creativa a esuat: fisierul si conceptul (hook-ul).
    return [
        CalibrationLesson.model_validate(row, from_attributes=True).model_copy(
            update={"asset_sha256": record.asset_sha256, "concept": record.concept}
        )
        for row, record in rows
    ]


def _terms(texts: Iterable[str]) -> set[str]:
    return {token for text in texts for token in tokenize(text) if len(token) >= _MIN_TERM}


def industry_terms(account: ClientAccount) -> set[str]:
    """Cuvintele care spun in ce industrie e clientul: numele, tipul afacerii, treaba JTBD."""
    avatar = avatar_from_answers(account.avatar_answers)
    return _terms([account.name, account.brand_name, account.business_kind, *avatar_texts(avatar)])


def _trend_text(industry: str, insight: str) -> str:
    """Ce se transforma in vector: industria si trendul, impreuna."""
    return f"{industry}. {insight}" if industry else insight


def retrieve_trends(
    session: Session,
    tenant_id: int,
    terms: set[str],
    *,
    platform: AdPlatform | None,
    today: date,
    embedder: Embedder | None = None,
    limit: int = MAX_TRENDS,
) -> list[TrendInsight]:
    """RAG-ul CCO-ului: trendurile agentiei si ale automatizarii, potrivite industriei.

    Un trend intra cand vectorul lui e aproape de industria clientului (acelasi model de
    embeddings) sau cand au cuvinte in comun; unul cu industria goala e general si intra
    dupa cele potrivite. Doar neexpirate, de pe platforma creativei sau pentru toate.
    Ordinea: potrivite intai, apoi similaritatea, cuvintele comune, cele mai noi.
    """
    rows = session.exec(
        select(CreativeTrend)
        .where(
            or_(col(CreativeTrend.tenant_id) == tenant_id, col(CreativeTrend.tenant_id).is_(None))
        )
        .where(CreativeTrend.expires_at >= today)
    ).all()
    query = " ".join(sorted(terms))
    vectors: dict[str, list[float] | None] = {}

    def query_vector(model: str) -> list[float] | None:
        if model not in vectors:
            vectors[model] = None
            if model == HASH_MODEL:
                vectors[model] = HashEmbedder().embed([query])[0]
            elif embedder is not None and model == embedder.model:
                # Ollama cazut: raman cuvintele comune.
                with suppress(ProviderError):
                    vectors[model] = embedder.embed([query])[0]
        return vectors[model]

    scored: list[tuple[tuple[int, float, int, date], CreativeTrend]] = []
    for row in rows:
        if platform is not None and row.platform not in (platform, "all"):
            continue
        overlap = len(_terms([row.industry]) & terms)
        similarity = 0.0
        vector = query_vector(row.embedding_model) if row.embedding and query else None
        if vector is not None and row.embedding is not None:
            similarity = cosine(vector, row.embedding)
        threshold = _MIN_SIMILARITY.get(row.embedding_model, _DEFAULT_MIN_SIMILARITY)
        matched = overlap > 0 or (vector is not None and similarity >= threshold)
        if not matched and row.industry.strip():
            continue  # alta industrie
        scored.append(((int(matched), similarity, overlap, row.observed_at), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        TrendInsight.model_validate(row, from_attributes=True) for _, row in scored[:limit]
    ]


def purge_old_trends(session: Session, today: date) -> int:
    """Sterge trendurile mai vechi de ``TREND_TTL_DAYS`` sau expirate; intoarce cate."""
    oldest = today - timedelta(days=TREND_TTL_DAYS)
    result = session.exec(
        delete(CreativeTrend).where(
            or_(col(CreativeTrend.observed_at) < oldest, col(CreativeTrend.expires_at) < today)
        )
    )
    session.commit()
    return int(result.rowcount or 0)


def ingest_trends(
    session: Session, body: TrendIngest, *, embedder: Embedder, today: date
) -> TrendIngestResult:
    """Trendurile automatizarii saptamanale: curata ce e vechi, apoi le salveaza cu vectori.

    Acelasi titlu pe aceeasi platforma se actualizeaza (cron-ul retrimite ce inca merge),
    nu se dubleaza. Un trend mai vechi de 30 de zile nu mai intra deloc.
    """
    deleted = purge_old_trends(session, today)
    oldest = today - timedelta(days=TREND_TTL_DAYS)
    fresh = [trend for trend in body.trends if (trend.observed_at or today) >= oldest]
    model, vectors = embed_or_fallback(
        embedder, [_trend_text(trend.industry, trend.insight()) for trend in fresh]
    )
    created = updated = 0
    for trend, vector in zip(fresh, vectors, strict=True):
        observed = trend.observed_at or today
        row = session.exec(
            select(CreativeTrend)
            .where(col(CreativeTrend.tenant_id).is_(None))
            .where(CreativeTrend.platform == trend.platform)
            .where(func.lower(CreativeTrend.title) == trend.title.strip().lower())
        ).first()
        if row is None:
            row = CreativeTrend(insight="", observed_at=observed, expires_at=observed)
            created += 1
        else:
            updated += 1
        row.platform = trend.platform
        row.industry = trend.industry.strip()
        row.title = trend.title.strip()
        row.hook = trend.hook.strip()
        row.visual_format = trend.visual_format.strip()
        row.virality_reason = trend.virality_reason.strip()
        row.insight = trend.insight()
        row.source = trend.source.strip()
        row.observed_at = observed
        row.expires_at = observed + timedelta(days=TREND_TTL_DAYS)
        row.embedding = vector
        row.embedding_model = model
        session.add(row)
    session.commit()
    return TrendIngestResult(
        received=len(body.trends),
        created=created,
        updated=updated,
        expired_deleted=deleted,
        embedding_model=model,
    )


def add_agency_trend(
    session: Session, tenant_id: int, trend: TrendInsight, *, valid_days: int, embedder: Embedder
) -> CreativeTrend:
    """O nota a agentiei in trends_db, cu vectorul ei."""
    model, [vector] = embed_or_fallback(
        embedder, [_trend_text(trend.industry.strip(), trend.insight.strip())]
    )
    row = CreativeTrend(
        tenant_id=tenant_id,
        platform=trend.platform,
        industry=trend.industry.strip(),
        insight=trend.insight.strip(),
        source=trend.source.strip(),
        observed_at=trend.observed_at,
        expires_at=trend.observed_at + timedelta(days=valid_days),
        embedding=vector,
        embedding_model=model,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def build_context(
    session: Session,
    account: ClientAccount,
    *,
    purpose: Purpose = "ad",
    platform: AdPlatform | None = None,
    alt_text: str | None = None,
    now: datetime | None = None,
    embedder: Embedder | None = None,
) -> CreativeEvaluationContext:
    """Tot ce trebuie sa stie CCO-ul de la ceilalti agenti inainte de evaluare.

    ``embedder`` = modelul de embeddings de pe server (``embedder_from_settings``); fara
    el, se folosesc doar trendurile cu vectori lexicali si cuvintele comune.
    """
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
            embedder=embedder,
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
        concept=str(result.get("concept") or "")[:300],
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
        # Fisierul si conceptul stau pe evaluare, nu pe fiecare corectie.
        fields = lesson.model_dump(exclude={"asset_sha256", "concept"})
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
            **fields,
        )
        for field, value in fields.items():
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
