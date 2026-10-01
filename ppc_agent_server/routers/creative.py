"""``POST /api/v1/creative/upload`` - CCO-ul evalueaza o creativa (``creative_evaluator.py``).

Doar pentru clientul autentificat (zona ``/cont``) si cu limita pe ora: un model cu
vision pe CPU tine minute intregi o imagine. Fisierul se citeste in memorie, cu
plafon de marime, si se verifica dupa semnatura (JPEG/PNG), nu dupa extensie.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ppc_agent_server.models import ClientUser
from ppc_agent_server.rate_limit import CREATIVE_HOURLY, too_many_requests
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.services.creative_evaluator import (
    MAX_IMAGE_BYTES,
    CreativeEvaluation,
    VisionModel,
    evaluate_creative,
    image_kind,
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
    """Evaluarea CCO-ului pentru imaginea incarcata: ``aesthetic_score``,
    ``virality_potential``, ``algorithm_compatibility`` si ``feedback``.

    Raises:
        HTTPException: 413 prea mare, 415 nu e JPEG/PNG, 429 peste limita pe ora.
        SetupRequiredError: modelul de vision nu e configurat sau nu raspunde (-> 503).
        ProviderError: modelul a picat sau a raspuns invalid (-> 502).
    """
    key = f"client:{user.client_account_id}"
    wait = CREATIVE_HOURLY.hit(key)
    if wait is not None:
        raise too_many_requests(wait, "Ai trimis multe creative la evaluat în ultima oră.")
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"imaginea depășește {MAX_IMAGE_BYTES // (1024 * 1024)} MB"
        )
    if image_kind(data) is None:
        raise HTTPException(status_code=415, detail="doar imagini JPEG sau PNG")
    return evaluate_creative(data, model=model)
