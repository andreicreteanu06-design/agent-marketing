"""Lansarea de campanii noi - doar ca PROPUNERE, niciodata direct.

``POST /propose_launch`` nu vorbeste cu Meta. Valideaza specificatia, verifica
plafonul de cheltuiala si depune o propunere ``CREATE_CAMPAIGN`` in asteptare,
cu specificatia completa in ``after`` - exact ce va vedea omul care aproba.
Campania apare in contul Meta abia dupa ``POST /api/v1/proposals/{id}/approve``,
si si atunci totul se creeaza OPRIT: activarea ramane un pas manual.

Deci intre cererea de lansare si primul leu cheltuit stau consiliul, CCO-ul si doua
decizii umane: avizul consiliului (``services/launch_council.py``), verdictul CCO-ului pe
imaginea reclamei (``services/creative_evaluator.py``), aprobarea in ``/cont`` si
activarea in Ads Manager. Cu oprirea de urgenta activa, nu se depune nimic (423).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ppc_agent.errors import PpcAgentError
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.live.meta import download_image
from ppc_agent.providers.meta_campaign import (
    DEFAULT_CALL_TO_ACTION,
    MetaAdCreative,
    MetaLaunchSpec,
    build_meta_campaign_payload,
    normalize_ad_account_id,
)
from ppc_agent.services.launch_brief import build_launch_brief
from ppc_agent_server.db import get_session
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ClientUser,
    ProposedChange,
)
from ppc_agent_server.routers import queen
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import CampaignLaunchRequest, ProposedChangeRead
from ppc_agent_server.services.avatar_builder import profile_missing
from ppc_agent_server.services.client_intake import launch_economics, open_intake
from ppc_agent_server.services.council import CouncilReply
from ppc_agent_server.services.council_guard import DECIDED_BY
from ppc_agent_server.services.creative_context import CreativeEvaluationContext
from ppc_agent_server.services.creative_evaluator import (
    MAX_IMAGE_BYTES,
    evaluate_creative,
    text_judge_from_settings,
    vision_model_from_settings,
)
from ppc_agent_server.services.creative_memory import build_context, save_evaluation
from ppc_agent_server.services.embeddings import embedder_from_settings
from ppc_agent_server.services.emergency_stop import require_running
from ppc_agent_server.services.launch_council import (
    REVIEW_KEY,
    Council,
    blocked_by,
    growth_block,
    launch_question,
    review,
)
from ppc_agent_server.settings import get_server_settings
from ppc_agent_server.spend_guard import check_spend_limit, committed_daily_spend

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

SOURCE_MODULE = "campaign_launch"


def get_launch_council() -> Council:
    """Dependinta: consiliul din chat, cu sursele live (injectabil in teste)."""

    def consult(session: Session, client_account_id: int, question: str) -> CouncilReply:
        llm = queen.get_llm_router()
        return queen._deliberate(
            session,
            client_account_id,
            question,
            voice=None,  # avizul e determinist: nu asteapta minute dupa modelul local
            system_one=queen.get_system_one(llm),
            seo_intent=queen.get_seo_intent(),
            traffic=queen.get_organic_traffic(),
        )

    return consult


#: CCO-ul pe imaginea unei lansari: verdictul (``CreativeEvaluation``) sau, cand nu poate
#: rula, ``{"unavailable": motiv}``.
#: Imaginea lansarii si ce stiu ceilalti agenti (avatar, ipoteza CMO, lectii, trenduri)
#: -> verdictul CCO-ului, cu ``asset_sha256`` cand evaluarea a rulat.
CreativeReview = Callable[[str, CreativeEvaluationContext], dict[str, Any]]
CREATIVE_KEY = "creative_review"
#: Verdictul care opreste lansarea: o creativa slaba se repara inainte sa cheltuie bani.
#: "HUMAN_REVIEW_REQUIRED" nu opreste - aprobarea e chiar acea verificare umana.
CREATIVE_BLOCKS = "REVISE_BEFORE_TEST"
CREATIVE_DECIDED_BY = "cco"


def get_creative_review() -> CreativeReview:
    """Dependinta: CCO-ul pe imaginea lansarii (injectabil in teste).

    Un CCO care nu poate rula (Ollama oprit, modelul lipsa, imaginea nedescarcabila) nu
    opreste lansarea: avizul spune ca evaluarea lipseste, iar omul decide la aprobare.
    """

    def evaluate(image_url: str, context: CreativeEvaluationContext) -> dict[str, Any]:
        settings = get_server_settings()
        try:
            image = asyncio.run(download_image(image_url, max_bytes=MAX_IMAGE_BYTES))
            result = evaluate_creative(
                image,
                model=vision_model_from_settings(settings),
                judge=text_judge_from_settings(settings),
                whisper_model=settings.whisper_model,
                elevenlabs_api_key=settings.elevenlabs_api_key,
                context=context,
            )
            return {**result, "asset_sha256": hashlib.sha256(image).hexdigest()}
        except (PpcAgentError, ValueError) as exc:
            return {"unavailable": str(exc)[:300]}

    return evaluate


def _creative_note(creative: dict[str, Any]) -> str:
    """Ce adauga verdictul CCO-ului la motivul propunerii."""
    decision = creative.get("decision")
    risks = "; ".join(creative.get("detected_risks", [])[:3])
    if decision is None:
        return (
            f"CCO: evaluarea creativei n-a putut rula ({creative.get('unavailable', '')}) - "
            "verific-o tu inainte de aprobare."
        )
    if decision == "HUMAN_REVIEW_REQUIRED":
        return f"CCO: creativa cere verificare umana - {risks}."
    if decision == CREATIVE_BLOCKS:
        return f"CCO: creativa trebuie revizuita inainte de test - {risks}."
    return "CCO: creativa e eligibila pentru test."


def _build_spec(payload: CampaignLaunchRequest, account: ClientAccount) -> MetaLaunchSpec:
    """Specificatia de lansare: cererea, completata cu setarile clientului.

    Raises:
        HTTPException: 422 cand specificatia nu trece validarea.
    """
    defaults = build_meta_campaign_payload(account.objective)
    try:
        return MetaLaunchSpec(
            campaign_name=payload.campaign_name.strip(),
            objective=account.objective,
            daily_budget=payload.daily_budget,
            pixel_id=payload.pixel_id,
            custom_event_type=(
                payload.custom_event_type
                or defaults["ad_set"]["promoted_object"]["custom_event_type"]
            ),
            page_id=payload.page_id,
            target_url=payload.target_url.strip(),
            headline=payload.headline.strip(),
            primary_text=payload.primary_text.strip(),
            image_url=payload.image_url.strip(),
            country=payload.country or account.geo.strip().upper(),
            call_to_action=payload.call_to_action or DEFAULT_CALL_TO_ACTION[account.objective],
            extra_ads=tuple(
                MetaAdCreative(
                    headline=ad.headline.strip(),
                    primary_text=ad.primary_text.strip(),
                    image_url=ad.image_url.strip(),
                    angle=ad.angle.strip(),
                )
                for ad in payload.extra_ads
            ),
            **_local_area(account),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _local_area(account: ClientAccount) -> dict[str, Decimal]:
    """Raza aleasa de consiliu pentru o afacere locala; ``{}`` = toata tara."""
    if account.service_area != "local" or account.target_radius_km is None:
        return {}
    if account.location_lat is None or account.location_lng is None:
        return {}
    return {
        "latitude": account.location_lat,
        "longitude": account.location_lng,
        "radius_km": account.target_radius_km,
    }


def _rationale(spec: MetaLaunchSpec, ad_account: str) -> str:
    """Ce citeste omul care aproba: cifre si consecinte, nu formule."""
    objective = build_meta_campaign_payload(spec.objective)["objective"]
    area = (
        f"o raza de {spec.radius_km} km in jurul afacerii"
        if spec.radius_km is not None
        else f"tara {spec.country}"
    )
    return (
        f"Lansare campanie Meta '{spec.campaign_name}' in contul {ad_account}: "
        f"{objective}, buget {spec.daily_budget} pe zi, optimizata pe evenimentul "
        f"{spec.custom_event_type} al pixelului {spec.pixel_id}, {area}. "
        "Dupa aprobare se creeaza campania, setul de reclame si anuntul, TOATE OPRITE "
        "(PAUSED) - nimic nu cheltuie pana nu le activezi manual din Ads Manager. "
        "Bugetul intra in plafonul zilnic din momentul aprobarii."
    )


@router.post("/propose_launch", response_model=ProposedChangeRead, status_code=201)
def propose_launch(
    payload: CampaignLaunchRequest,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
    council: Annotated[Council, Depends(get_launch_council)],
    creative_review: Annotated[CreativeReview, Depends(get_creative_review)],
) -> ProposedChange:
    """Depune o propunere de lansare, cu avizul consiliului. Nu creeaza nimic in Meta.

    Raises:
        HTTPException: 423 cu oprirea de urgenta activa; 409 cand contul Meta nu e
            configurat; 422 cand specificatia nu e valida sau cand brief-ul gaseste o
            problema obiectiva (pagina de destinatie care nu exista sau nu e publica);
            503 cand consiliul nu poate delibera - fara aviz, nu se lanseaza nimic.
        SpendLimitExceeded: bugetul ar depasi plafonul zilnic (-> 409).

    Consiliul delibereaza pe lansare cu toate datele clientului; avizul lui sta in
    ``before["council_review"]``. Daca dupa deliberare exista un veto pe bani sau o
    inghetare a cheltuielilor, propunerea se scrie ``blocked``, cu motivul - clientul
    o vede in ``GET /proposals/blocked`` si nu o poate aproba.

    Plafonul se verifica aici ca sa nu intre in coada o lansare care n-ar
    putea fi aprobata oricum - si se verifica DIN NOU la aprobare, fiindca
    intre timp se pot fi executat alte propuneri.

    Inainte de a intra in coada, propunerea primeste brief-ul de lansare
    (``services/launch_brief.py``): pagina de destinatie vazuta de agentul
    SEO/GEO, faza de invatare si pozitia in cont calculate de agentul PPC,
    semnalele din Search Console, Keyword Planner si Business Profile. Brief-ul
    sta in ``before`` - contextul in care s-a luat decizia - langa
    specificatia din ``after``.
    """
    require_running(session)
    account = session.get(ClientAccount, client_user.client_account_id)
    if account is None:  # pragma: no cover - FK garanteaza existenta
        raise HTTPException(status_code=404, detail="contul clientului nu exista")
    if account.economics_confirmed_at is None or profile_missing(account.avatar_answers):
        question = open_intake(session, account)
        raise HTTPException(
            status_code=409,
            detail=(
                "Înainte de prima campanie, consiliul are nevoie de costurile tale, de zona în "
                "care sunt clienții și de câteva vorbe despre ei: din ele calculează cât poți "
                "plăti pe un client fără să pierzi bani și ce îi oprește să cumpere. Răspunde "
                "în chat la întrebări" + (f" - prima: {question}" if question else ".")
            ),
        )

    config = _app_config_for(account)
    raw_ad_account = config.settings.meta_ad_account_id
    if not raw_ad_account:
        raise HTTPException(
            status_code=409,
            detail=(
                "contul de reclame Meta nu e configurat pentru acest client - "
                "fara el nu stim unde s-ar crea campania."
            ),
        )
    try:
        ad_account = normalize_ad_account_id(raw_ad_account)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    spec = _build_spec(payload, account)
    check_spend_limit(session, account, spec.daily_budget)

    brief = build_launch_brief(
        ProviderFactory(config),
        config,
        spec,
        ad_account=ad_account,
        committed_daily_spend=committed_daily_spend(session, account.id or 0),
    )
    if brief.blocking:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "lansarea nu poate intra in coada: " + "; ".join(brief.blocking),
                "blocking": brief.blocking,
                "brief": brief.to_payload(),
            },
        )

    client_id = account.id or 0
    economics = launch_economics(account, spec.daily_budget)
    question = launch_question(spec.campaign_name, spec.daily_budget)
    if economics is not None:
        question += f" {economics['note']}"
    try:
        reply = council(session, client_id, question)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="consiliul nu a putut delibera acum - fără avizul lui nu se lansează nimic",
        ) from exc
    # Dupa deliberare: o taietura a CFO-ului de acum e deja in memorie, deci conteaza.
    block = growth_block(session, client_id)
    # CCO-ul afla de la ceilalti agenti pe ce sa judece: clientul ideal, ipoteza CMO-ului,
    # lectiile din piata ale contului, ce merge acum pe Meta.
    context = build_context(
        session, account, purpose="ad", platform="meta",
        embedder=embedder_from_settings(get_server_settings()),
    )
    creative = creative_review(spec.image_url, context)
    sha = str(creative.pop("asset_sha256", ""))
    if creative.get("decision") is not None:  # verdictul se pastreaza: PPC-ul ii va raspunde
        creative["evaluation_id"] = save_evaluation(session, client_id, sha, creative, context)
    # Reclamele in plus trec prin aceeasi poarta: una slaba nu intra in cont doar
    # fiindca nu e prima.
    extra_creatives = []
    for position, extra in enumerate(spec.extra_ads, start=2):
        extra_review = dict(creative_review(extra.image_url, context))
        extra_sha = str(extra_review.pop("asset_sha256", ""))
        if extra_review.get("decision") is not None:
            extra_review["evaluation_id"] = save_evaluation(
                session, client_id, extra_sha, extra_review, context
            )
        extra_review["ad_position"] = position
        extra_creatives.append(extra_review)
    blocked_extra = next(
        (item for item in extra_creatives if item.get("decision") == CREATIVE_BLOCKS), None
    )

    proposal = ProposedChange(
        client_account_id=client_id,
        op=ChangeOp.CREATE_CAMPAIGN,
        # Tinta e contul de reclame: campania nu exista inca, deci n-are id.
        # Contul ramane inghetat in propunere - se creeaza exact acolo unde
        # scria cand omul a aprobat, chiar daca setarea clientului se schimba.
        resource=f"meta_ad_account/{ad_account}",
        resource_type="campaign",
        before={
            **brief.to_payload(),
            REVIEW_KEY: review(reply),
            CREATIVE_KEY: creative,
            **({"extra_creative_reviews": extra_creatives} if extra_creatives else {}),
            "economics": economics,
        },
        after=spec.to_payload(),
        projected_daily_spend=spec.daily_budget,
        rationale=(
            f"{_rationale(spec, ad_account)} {brief.summary()} "
            + (f"{economics['note']} " if economics else "")
            + f"Consiliul: {reply.ruling.decision} {_creative_note(creative)}"
        ),
        source_module=SOURCE_MODULE,
        status=ChangeStatus.PENDING,
    )
    if block is not None:
        stopped = blocked_by(block)
        proposal.status = ChangeStatus.BLOCKED
        proposal.decided_at = reply.generated_at
        proposal.decided_by = DECIDED_BY
        proposal.error_message = stopped["message"]
        proposal.before = {**proposal.before, "council": stopped["context"]}
    elif creative.get("decision") == CREATIVE_BLOCKS or blocked_extra is not None:
        weak = creative if creative.get("decision") == CREATIVE_BLOCKS else blocked_extra
        assert weak is not None
        position = 1 if weak is creative else weak["ad_position"]
        fixes = "; ".join(weak.get("priority_fixes", []))
        proposal.status = ChangeStatus.BLOCKED
        proposal.decided_at = reply.generated_at
        proposal.decided_by = CREATIVE_DECIDED_BY
        proposal.error_message = (
            f"Oprită de evaluarea creativă (reclama {position}): {_creative_note(weak)} "
            f"Repară: {fixes}. Apoi propune lansarea din nou, cu imaginea nouă."
        )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
