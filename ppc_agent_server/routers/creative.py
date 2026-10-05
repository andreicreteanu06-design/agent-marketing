"""CCO-ul (``creative_evaluator.py``) si bucla lui cu ceilalti agenti.

- ``POST /upload`` (client): imagine (JPEG/PNG, max 5 MB) sau video scurt (MP4/MOV/WebM,
  max 50 MB), verificate dupa semnatura, nu dupa extensie, cu limita pe ora (un model cu
  vision pe CPU tine minute intregi o evaluare). ``purpose=page`` = imagine pentru landing
  page/blog, judecata pe GEO (cu ``alt_text``-ul din pagina). Verdictul se pastreaza:
  ``evaluation_id``.
- ``POST /evaluations/{id}/ad`` (client): creativa a ajuns intr-un anunt lansat direct din
  Ads Manager - legatura de care are nevoie feedback-ul de noapte.
- ``POST /feedback`` (agentia, intern): PPC-ul trimite cifrele din piata (hook rate, CTR,
  ROAS); ce a prezis gresit CCO-ul devine o corectie (``performancecalibration``).
- ``POST``/``GET /trends`` (agentia): notele ei in trends_db - ce merge acum pe Meta/TikTok.
  Trendurile automatizarii saptamanale intra prin ``POST /api/v1/trends/ingest``
  (``routers/trends.py``).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from ppc_agent_server.auth import get_current_tenant
from ppc_agent_server.db import get_session
from ppc_agent_server.models import (
    ClientAccount,
    ClientUser,
    CreativeEvaluationRecord,
    CreativeTrend,
    Tenant,
)
from ppc_agent_server.rate_limit import CREATIVE_HOURLY, too_many_requests
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.creative_context import (
    TREND_TTL_DAYS,
    AdPlatform,
    CalibrationLesson,
    PerformanceFeedback,
    Purpose,
    TrendInsight,
)
from ppc_agent_server.services.creative_evaluator import (
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    CreativeEvaluation,
    TextJudge,
    VisionModel,
    asset_kind,
    evaluate_creative,
    text_judge_from_settings,
    vision_model_from_settings,
)
from ppc_agent_server.services.creative_memory import (
    FeedbackError,
    add_agency_trend,
    build_context,
    link_ad,
    record_feedback,
    save_evaluation,
)
from ppc_agent_server.services.embeddings import embedder_from_settings
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/creative", tags=["creative"])


class AdLink(BaseModel):
    """Anuntul in care a ajuns o creativa evaluata."""

    platform: AdPlatform
    ad_id: str = Field(min_length=1, max_length=64)


class TrendCreate(TrendInsight):
    """O nota noua in trends_db; expira dupa ``valid_days`` (cel mult 30: date proaspete)."""

    valid_days: int = Field(default=TREND_TTL_DAYS, ge=1, le=TREND_TTL_DAYS)


class TrendRead(TrendInsight):
    id: int
    expires_at: date


def get_vision_model() -> VisionModel:
    """Dependinta: modelul cu vision, sau 503 daca nu e configurat."""
    return vision_model_from_settings(get_server_settings())


def get_text_judge() -> TextJudge:
    """Dependinta: Jev, sau 503 daca lipseste JEV_API_KEY."""
    return text_judge_from_settings(get_server_settings())


@router.post("/upload", response_model=CreativeEvaluation)
def upload_creative(
    file: UploadFile,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    model: Annotated[VisionModel, Depends(get_vision_model)],
    judge: Annotated[TextJudge, Depends(get_text_judge)],
    session: Annotated[Session, Depends(get_session)],
    purpose: Annotated[Purpose, Form()] = "ad",
    platform: Annotated[AdPlatform | None, Form()] = None,
    alt_text: Annotated[str | None, Form(max_length=500)] = None,
) -> dict[str, object]:
    """Verdictul CCO-ului: ``asset_type``, ``decision``, ``scores``, ``detected_risks``,
    ``priority_fixes``, ``context_notes``, ``evaluation_id`` si, la video, ``video_facts``.

    Inainte de evaluare, CCO-ul afla de la ceilalti agenti avatarul JTBD, ipoteza
    CMO-ului, lectiile din piata ale contului si trendurile (``build_context``).

    Raises:
        HTTPException: 413 prea mare, 415 tip nesuportat, 422 fisier ilizibil sau video
            peste 3 minute, 429 peste limita pe ora.
        SetupRequiredError: modelul de vision, JEV_API_KEY, ffmpeg, tesseract sau modelul
            whisper lipsesc (-> 503).
        ProviderError: modelul a picat sau a raspuns invalid (-> 502).
    """
    key = f"client:{user.client_account_id}"
    wait = CREATIVE_HOURLY.hit(key)
    if wait is not None:
        raise too_many_requests(wait, "Ai trimis multe creative la evaluat în ultima oră.")
    data = file.file.read(MAX_VIDEO_BYTES + 1)
    kind = asset_kind(data)
    if kind is None:
        raise HTTPException(
            status_code=415, detail="doar imagini JPEG/PNG sau video MP4/MOV/WebM"
        )
    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"fișierul depășește {limit // (1024 * 1024)} MB"
        )
    settings = get_server_settings()
    account = session.get(ClientAccount, user.client_account_id)
    assert account is not None  # FK-ul garanteaza contul
    context = build_context(
        session, account, purpose=purpose, platform=platform, alt_text=alt_text,
        embedder=embedder_from_settings(settings),
    )
    try:
        result = evaluate_creative(
            data,
            model=model,
            judge=judge,
            whisper_model=settings.whisper_model,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            context=context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["evaluation_id"] = save_evaluation(
        session, account.id or 0, hashlib.sha256(data).hexdigest(), result, context
    )
    return result


@router.post("/evaluations/{evaluation_id}/ad", status_code=204)
def link_evaluation_to_ad(
    evaluation_id: int,
    body: AdLink,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    """Creativa evaluata ruleaza in anuntul ``ad_id``: de acum, PPC-ul ii trimite cifrele."""
    record = session.get(CreativeEvaluationRecord, evaluation_id)
    if record is None or record.client_account_id != user.client_account_id:
        raise HTTPException(status_code=404, detail="evaluarea nu există")
    link_ad(session, record, platform=body.platform, ad_id=body.ad_id)


@router.post("/feedback", response_model=list[CalibrationLesson])
def creative_feedback(
    feedback: PerformanceFeedback,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> list[CalibrationLesson]:
    """PPC -> CCO (intern, cu cheia agentiei): cifrele din piata ale unei creative judecate.

    Intoarce corectiile scrise - goala cand CCO-ul a prezis bine sau esantionul e mic.
    """
    record = session.get(CreativeEvaluationRecord, feedback.evaluation_id)
    account = session.get(ClientAccount, record.client_account_id) if record else None
    if account is None or account.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="evaluarea nu există")
    try:
        return record_feedback(session, account.id or 0, feedback)
    except FeedbackError as exc:  # pragma: no cover - verificat mai sus
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/trends", response_model=TrendRead, status_code=201)
def add_trend(
    body: TrendCreate,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> TrendRead:
    """O nota in trends_db: ce merge acum pe o platforma, intr-o industrie (cu vectorul ei)."""
    trend = add_agency_trend(
        session,
        tenant.id or 0,
        body,
        valid_days=body.valid_days,
        embedder=embedder_from_settings(get_server_settings()),
    )
    return TrendRead.model_validate(trend, from_attributes=True)


@router.get("/trends", response_model=list[TrendRead])
def list_trends(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    session: Annotated[Session, Depends(get_session)],
) -> list[TrendRead]:
    """Notele neexpirate ale agentiei, cele mai noi primele."""
    today = datetime.now(tz=UTC).date()
    rows = session.exec(
        select(CreativeTrend)
        .where(CreativeTrend.tenant_id == tenant.id)
        .where(CreativeTrend.expires_at >= today)
        .order_by(col(CreativeTrend.observed_at).desc())
    ).all()
    return [TrendRead.model_validate(row, from_attributes=True) for row in rows]
