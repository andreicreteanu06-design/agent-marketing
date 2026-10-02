"""``POST /api/v1/creative/upload`` - CCO-ul evalueaza o creativa (``creative_evaluator.py``).

Imagine (JPEG/PNG, max 5 MB) sau video scurt (MP4/MOV/WebM, max 50 MB), verificate dupa
semnatura, nu dupa extensie. Doar pentru clientul autentificat (zona ``/cont``) si cu
limita pe ora: un model cu vision pe CPU tine minute intregi o evaluare.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ppc_agent_server.models import ClientUser
from ppc_agent_server.rate_limit import CREATIVE_HOURLY, too_many_requests
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.creative_evaluator import (
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    CreativeEvaluation,
    VisionModel,
    asset_kind,
    evaluate_creative,
    vision_model_from_settings,
)
from ppc_agent_server.settings import get_server_settings

router = APIRouter(prefix="/api/v1/creative", tags=["creative"])


def get_vision_model() -> VisionModel:
    """Dependinta: modelul cu vision, sau 503 daca nu e configurat."""
    return vision_model_from_settings(get_server_settings())


@router.post("/upload", response_model=CreativeEvaluation)
def upload_creative(
    file: UploadFile,
    user: Annotated[ClientUser, Depends(get_current_client_user)],
    model: Annotated[VisionModel, Depends(get_vision_model)],
) -> dict[str, object]:
    """Verdictul CCO-ului: ``asset_type``, ``decision``, ``scores``, ``detected_risks``,
    ``priority_fixes`` si, la video, ``video_facts`` (durata, taieturi, voce, muzica).

    Raises:
        HTTPException: 413 prea mare, 415 tip nesuportat, 422 fisier ilizibil sau video
            peste 3 minute, 429 peste limita pe ora.
        SetupRequiredError: modelul de vision, ffmpeg sau modelul whisper lipsesc (-> 503).
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
    try:
        return evaluate_creative(
            data,
            model=model,
            whisper_model=settings.whisper_model,
            elevenlabs_api_key=settings.elevenlabs_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
