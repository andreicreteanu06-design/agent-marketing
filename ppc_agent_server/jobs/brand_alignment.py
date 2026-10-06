"""Muschiul asculta de Regina: directiva de brand devine propuneri de rescriere.

Regina (``services/queen_agent.py``) doar sfatuieste - intoarce o directiva si
atat. Aici, pe partea PPC, se decide ce se face cu ea: fiecare reclama pe care
Regina o gaseste deviata de la clientul ideal devine o propunere ``UPDATE``
(rescriere de text) in starea ``pending``, chiar daca CPA-ul ei pare stabil -
formulele Kelly/Thompson judeca bani, nu cui ii vorbeste reclama.

Aceleasi reguli ca la evaluatorul autonom:

1. **Nu atinge niciun cont de reclame.** Singura scriere e un rand in
   ``ProposedChange``. O rescriere de text nu are executor (nici pe Meta, nici
   in coada de copy): la aprobare, motorul de executie o refuza explicit, iar
   omul o aplica in platforma - sau cu copywriterul, cu declansatorul din ``after``.
2. **Nu propune de doua ori acelasi lucru.** O reclama cu o rescriere deja in
   asteptare e sarita.
3. **Nu muta bani.** ``projected_daily_spend`` e 0: textul nu schimba bugetul,
   iar garda de cheltuieli numara doar ce se executa.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlmodel import Session, select

from ppc_agent.creative.concepts import concept_brief
from ppc_agent_server.models import ChangeOp, ChangeStatus, ClientAccount, ProposedChange
from ppc_agent_server.services.propensity import SENSITIVE_LABELS
from ppc_agent_server.services.queen_agent import (
    AdAlignment,
    BrandStrategist,
    BrandStrategyDirective,
)
from ppc_agent_server.services.queen_signals import DbBrandSignals

logger = logging.getLogger("ppc_agent_server.jobs.brand_alignment")

SOURCE_MODULE = "queen_agent"
#: Tipul de resursa al propunerilor de aici. Serveste si la deduplicare.
RESOURCE_TYPE = "ad_copy"


def consult_queen(
    session: Session, client_account_id: int, *, strategist: BrandStrategist | None = None
) -> BrandStrategyDirective:
    """Cere Reginei directiva pentru un client (fara nicio scriere)."""
    queen = strategist or BrandStrategist(DbBrandSignals(session))
    return queen.evaluate_brand_alignment(client_account_id)


def _pending_refs(session: Session, client_account_id: int) -> set[str]:
    rows = session.exec(
        select(ProposedChange.resource)
        .where(ProposedChange.client_account_id == client_account_id)
        .where(ProposedChange.resource_type == RESOURCE_TYPE)
        .where(ProposedChange.status == ChangeStatus.PENDING)
        .where(ProposedChange.source_module == SOURCE_MODULE)
    ).all()
    return {str(row) for row in rows}


def to_rewrite_proposal(
    client_account_id: int, ad: AdAlignment, directive: BrandStrategyDirective
) -> ProposedChange:
    """Propunerea de rescriere pentru o reclama deviata de la clientul ideal."""
    avatar = directive.avatar
    angle = directive.copywriting_angle
    if avatar is None or angle is None:
        raise ValueError("o directiva fara client ideal nu poate cere rescrieri")
    brief: dict[str, Any] = {
        "avatar": avatar.name,
        "avatar_key": avatar.key,
        "copy_brief": angle.summary,
        "emotion_trigger": angle.emotion_trigger,
        "tone": angle.tone,
        "hooks": angle.hooks,
        "must_include": angle.must_include,
        "avoid": angle.avoid,
    }
    psychology = directive.cognitive_profile
    if psychology is not None:
        # Copywriterul primeste si DE CE: cum decide publicul si ce parghie folosim.
        brief["psychology"] = {
            "decision_mode": psychology.decision_mode.system,
            "conversion_barrier": psychology.barrier.kind,
            "persuasion_route": psychology.persuasion_route.route,
            "persuasion_lever": psychology.lever,
            "needs": psychology.decision_mode.needs,
            "cognitive_note": ad.cognitive_note,
        }
    if directive.customer_avatar is not None:
        brief["customer_avatar"] = directive.customer_avatar.model_dump()
    if directive.experiment is not None:
        # Rescrierea e varianta unui test, nu un text aruncat: ipoteza si cum se judeca.
        brief["experiment"] = directive.experiment.model_dump()
        # Si structura reclamei: sablonul de concept ales de CMO pentru bariera.
        brief["concept"] = concept_brief(directive.experiment.concept_template)
    if directive.sensitive_domain is not None:
        brief["guardrails"] = {
            "fear_manipulation_risk": (
                f"blocat: domeniu sensibil ({SENSITIVE_LABELS[directive.sensitive_domain]}) - "
                "fără frică, fără ton alarmist"
            )
        }
    return ProposedChange(
        client_account_id=client_account_id,
        op=ChangeOp.UPDATE,
        resource=ad.ref,
        resource_type=RESOURCE_TYPE,
        before={
            "platform": ad.platform,
            "headline": ad.headline,
            "text": ad.text,
            "speaks_to": ad.speaks_to,
            "avatar_stance": ad.avatar_stance,
            "alignment_score": ad.alignment_score,
            "cpa": None if ad.cpa is None else str(ad.cpa),
            "target_cpa": None if ad.target_cpa is None else str(ad.target_cpa),
        },
        after=brief,
        # Textul nu muta bugetul - vezi punctul 3 din docstring-ul modulului.
        projected_daily_spend=Decimal("0"),
        rationale=(
            f"[Regina] {ad.reason} Rescrie pentru «{avatar.name}» "
            f"({avatar.share * 100:.0f}% din ce aduce contul): {angle.summary} "
            f"Declanșator pentru copywriter: «{angle.emotion_trigger}». Nu se aplică "
            "automat - rescrie textul în platformă după aprobare."
        ),
        source_module=SOURCE_MODULE,
        status=ChangeStatus.PENDING,
    )


def publish_hypothesis(
    session: Session, client_account_id: int, directive: BrandStrategyDirective
) -> None:
    """CMO -> CCO: ipoteza de acum (experimentul pe bariera dominanta), pe contul clientului.

    CCO-ul o citeste inainte de fiecare evaluare (``creative_memory.build_context``) si
    respinge reclamele care nu o respecta. Fara experiment, ipoteza veche se sterge.
    """
    account = session.get(ClientAccount, client_account_id)
    if account is None:
        return
    experiment = directive.experiment
    account.cmo_hypothesis = experiment.model_dump(mode="json") if experiment else None
    session.add(account)
    session.commit()


def apply_brand_directive(
    session: Session, client_account_id: int, *, strategist: BrandStrategist | None = None
) -> dict[str, Any]:
    """Cere directiva si depune rescrierile cerute de ea ca propuneri in asteptare.

    Returns:
        Rezumatul: starea directivei, clientul ideal, unghiul si cate propuneri
        s-au creat. Nu aplica nimic pe vreo platforma.
    """
    directive = consult_queen(session, client_account_id, strategist=strategist)
    publish_hypothesis(session, client_account_id, directive)
    misaligned = directive.misaligned_ads
    summary: dict[str, Any] = {
        "status": directive.status,
        "avatar": directive.avatar.name if directive.avatar else None,
        "avatar_share": directive.avatar.share if directive.avatar else None,
        "copywriting_angle": (
            directive.copywriting_angle.summary if directive.copywriting_angle else None
        ),
        "ads_evaluated": len(directive.ad_alignment),
        "misaligned": len(misaligned),
        "proposed": 0,
        "skipped_duplicates": 0,
    }
    if not misaligned:
        return summary

    already_pending = _pending_refs(session, client_account_id)
    for ad in misaligned:
        if ad.ref in already_pending:
            summary["skipped_duplicates"] += 1
            continue
        session.add(to_rewrite_proposal(client_account_id, ad, directive))
        summary["proposed"] += 1
        logger.info(
            "[Regina] client %s: rescriere PENDING pentru %s (vorbeste %s, nu %s).",
            client_account_id,
            ad.ref,
            ad.speaks_to or "nimanui",
            directive.avatar.key if directive.avatar else "-",
        )
    session.commit()
    return summary
