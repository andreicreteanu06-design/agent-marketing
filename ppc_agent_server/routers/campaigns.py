"""Lansarea de campanii noi - doar ca PROPUNERE, niciodata direct.

``POST /propose_launch`` nu vorbeste cu Meta. Valideaza specificatia, verifica
plafonul de cheltuiala si depune o propunere ``CREATE_CAMPAIGN`` in asteptare,
cu specificatia completa in ``after`` - exact ce va vedea omul care aproba.
Campania apare in contul Meta abia dupa ``POST /api/v1/proposals/{id}/approve``,
si si atunci totul se creeaza OPRIT: activarea ramane un pas manual.

Deci intre cererea de lansare si primul leu cheltuit stau doua decizii umane:
aprobarea in ``/cont`` si activarea in Ads Manager.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ppc_agent.providers.meta_campaign import (
    DEFAULT_CALL_TO_ACTION,
    MetaLaunchSpec,
    build_meta_campaign_payload,
    normalize_ad_account_id,
)
from ppc_agent_server.db import get_session
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ClientUser,
    ProposedChange,
)
from ppc_agent_server.routers.client_auth import get_current_client_user
from ppc_agent_server.schemas import CampaignLaunchRequest, ProposedChangeRead
from ppc_agent_server.spend_guard import check_spend_limit

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

SOURCE_MODULE = "campaign_launch"


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _rationale(spec: MetaLaunchSpec, ad_account: str) -> str:
    """Ce citeste omul care aproba: cifre si consecinte, nu formule."""
    objective = build_meta_campaign_payload(spec.objective)["objective"]
    return (
        f"Lansare campanie Meta '{spec.campaign_name}' in contul {ad_account}: "
        f"{objective}, buget {spec.daily_budget} pe zi, optimizata pe evenimentul "
        f"{spec.custom_event_type} al pixelului {spec.pixel_id}, tara {spec.country}. "
        "Dupa aprobare se creeaza campania, setul de reclame si anuntul, TOATE OPRITE "
        "(PAUSED) - nimic nu cheltuie pana nu le activezi manual din Ads Manager. "
        "Bugetul intra in plafonul zilnic din momentul aprobarii."
    )


@router.post("/propose_launch", response_model=ProposedChangeRead, status_code=201)
def propose_launch(
    payload: CampaignLaunchRequest,
    client_user: Annotated[ClientUser, Depends(get_current_client_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProposedChange:
    """Depune o propunere de lansare. Nu creeaza nimic in Meta.

    Raises:
        HTTPException: 409 cand contul Meta nu e configurat, 422 cand
            specificatia nu e valida.
        SpendLimitExceeded: bugetul ar depasi plafonul zilnic (-> 409).

    Plafonul se verifica aici ca sa nu intre in coada o lansare care n-ar
    putea fi aprobata oricum - si se verifica DIN NOU la aprobare, fiindca
    intre timp se pot fi executat alte propuneri.
    """
    account = session.get(ClientAccount, client_user.client_account_id)
    if account is None:  # pragma: no cover - FK garanteaza existenta
        raise HTTPException(status_code=404, detail="contul clientului nu exista")

    raw_ad_account = _app_config_for(account).settings.meta_ad_account_id
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

    proposal = ProposedChange(
        client_account_id=account.id or 0,
        op=ChangeOp.CREATE_CAMPAIGN,
        # Tinta e contul de reclame: campania nu exista inca, deci n-are id.
        # Contul ramane inghetat in propunere - se creeaza exact acolo unde
        # scria cand omul a aprobat, chiar daca setarea clientului se schimba.
        resource=f"meta_ad_account/{ad_account}",
        resource_type="campaign",
        before={},
        after=spec.to_payload(),
        projected_daily_spend=spec.daily_budget,
        rationale=_rationale(spec, ad_account),
        source_module=SOURCE_MODULE,
        status=ChangeStatus.PENDING,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
