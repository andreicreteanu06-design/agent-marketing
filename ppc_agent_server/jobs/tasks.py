"""Task-urile efective: wrapper-e subtiri peste pipeline-urile pure din ``ppc_agent``.

Fiecare functie isi deschide propria sesiune DB (nu primeste una de la apelant)
si accepta doar argumente serializabile — functioneaza identic fie apelata
inline (``InlineJobQueue``, Faza E), fie intr-un proces worker ARQ separat
(Faza F), unde nu exista nicio sesiune HTTP de mostenit.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlmodel import Session, col, delete, select, update

from ppc_agent.alignment.pipeline import run_alignment
from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.config import AppConfig, BudgetConfig, ProviderMode, Settings
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.creative.creative_pipeline import generate_full_ad_creative
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.decision.pipeline import arms_from_performance, run_plan
from ppc_agent.guardrails.models import ProposedChange as CliProposedChange
from ppc_agent.guardrails.pipeline import build_fatigue_changes, build_proposed_changes
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent.ingestion.pipeline import run_ingestion
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent_server.db import get_engine
from ppc_agent_server.jobs.brand_alignment import apply_brand_directive
from ppc_agent_server.jobs.synthetic import run_tracking_contract_job, site_url
from ppc_agent_server.models import (
    AdPerformanceRecord,
    AdQueueItem,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    CreativeArtifact,
    EmergencyStop,
    Platform,
    PlatformArmSnapshot,
    ProposedChange,
    SiteAuditSnapshot,
    SiteSpeedSample,
)
from ppc_agent_server.security import decrypt_secret
from ppc_agent_server.services.council import build_financial_snapshot
from ppc_agent_server.services.council_guard import (
    COUNCIL_MEMORY_DAYS,
    DECIDED_BY,
    MONEY_MODULES,
    CouncilBlock,
    CouncilConstraints,
    GuardedChange,
    blocked_message,
    council_constraints,
    council_context,
    guard_changes,
)
from ppc_agent_server.services.memory import memory_line
from ppc_agent_server.services.queen_signals import (
    DbFinancialSignals,
    DbMemory,
    DbTechnicalSignals,
)
from ppc_agent_server.services.technician import evaluate_technical_health
from ppc_agent_server.tracking.pipeline import to_ad_performance_state
from seo_geo_agent.audit.issues import AUDIT_ISSUE_TYPES
from seo_geo_agent.audit.service import AuditConfig, AuditResult, run_audit
from seo_geo_agent.audit.url_policy import CrawlTargetBlockedError, normalize_and_validate_start_url
from seo_geo_agent.external_data import fetch_pagespeed_insights
from seo_geo_agent.settings import get_seo_geo_settings

logger = logging.getLogger("ppc_agent_server.jobs.tasks")

AdPlatform = Literal["google", "tiktok"]
_MOCK_CUSTOMER_ID = "mock-customer"
_MOCK_ADVERTISER_ID = "mock-advertiser"
_MOCK_AD_ACCOUNT_ID = "mock-account"


class ClientNotFoundError(ValueError):
    """Clientul referit de job nu exista — eroare de date, nu de infrastructura."""


def _app_config_for(account: ClientAccount) -> AppConfig:
    """Construieste un :class:`AppConfig` CLI-compatibil dintr-un rand ``ClientAccount``.

    ``settings=Settings()`` citeste ``PPC_PROVIDER_MODE`` (si restul) din mediu,
    exact ca la CLI — serverul nu reinventeaza o a doua sursa de configurare.

    ``default_lead_value`` alimenteaza ``budget.target_cpa``: acelasi camp
    serveste deja drept proxy de valoare pentru urmarirea conversiilor (vezi
    ``tracking/qualification.py``) si drept ``target_cpa`` la crearea unui
    ``AdPerformanceRecord`` nou (vezi ``tracking/pipeline.py``) — reutilizat
    aici ca sa activeze automat sfatul de capacitate per buget
    (``decision.budget_strategy``) pentru fiecare client, fara camp nou.

    Cand clientul si-a conectat propriile conturi de reclame (``*_enc`` pe
    ``ClientAccount``, criptate — vezi ``routers/client_auth.py``), acele
    secrete decriptate suprascriu ``Settings()`` global doar pentru campurile
    prezente; un client care n-a conectat inca nimic foloseste in continuare
    ``.env``-ul global neschimbat (comportament CLI/single-business identic
    cu azi — niciun test existent nu se schimba).
    """
    base_settings = Settings()
    overrides: dict[str, str] = {}
    if account.google_ads_refresh_token_enc:
        overrides["google_ads_refresh_token"] = decrypt_secret(
            account.google_ads_refresh_token_enc
        )
    if account.meta_access_token_enc:
        overrides["meta_access_token"] = decrypt_secret(account.meta_access_token_enc)
    if account.tiktok_access_token_enc:
        overrides["tiktok_access_token"] = decrypt_secret(account.tiktok_access_token_enc)
    if account.gsc_refresh_token_enc:
        # Search Console si Business Profile folosesc acelasi camp OAuth - vezi
        # nota din config.py: un singur token, dar consimtamantul trebuie sa
        # acopere ambele scope-uri.
        overrides["google_oauth_refresh_token"] = decrypt_secret(
            account.gsc_refresh_token_enc
        )
    if account.gsc_site_url:
        overrides["gsc_site_url"] = account.gsc_site_url
    # Identificatorii de cont, nu doar secretele: fara ei, ``run_plan`` citea
    # conturile GLOBALE din .env pentru TOTI clientii - adica propunerile unui
    # client s-ar fi generat din campaniile altuia. ``run_metrics_sync_job``
    # folosea deja valorile de pe ``ClientAccount``; asta aliniaza restul.
    for field, setting in (
        ("google_ads_customer_id", "google_ads_customer_id"),
        ("meta_ad_account_id", "meta_ad_account_id"),
        ("tiktok_advertiser_id", "tiktok_advertiser_id"),
    ):
        value = getattr(account, field)
        if value:
            overrides[setting] = value
    settings = base_settings.model_copy(update=overrides) if overrides else base_settings

    return AppConfig(
        target_domain=account.target_domain,
        geo=account.geo,
        language=account.language,
        budget=BudgetConfig(
            max_daily_spend=account.max_daily_spend,
            target_cpa=account.default_lead_value,
            lead_value=(
                account.default_lead_value
                if account.objective is CampaignObjective.LEAD_GEN
                else None
            ),
        ),
        settings=settings,
    )


def _require_client(session: Session, client_account_id: int) -> ClientAccount:
    account = session.get(ClientAccount, client_account_id)
    if account is None:
        raise ClientNotFoundError(f"clientul {client_account_id} nu exista")
    return account


def run_plan_job(*, client_account_id: int) -> dict[str, Any]:
    """Job Modulul 2: Kelly + Thompson + Markov (Google + Meta + TikTok combinate)."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = ProviderFactory(config)
        plan = run_plan(factory, config)
        return plan.model_dump(mode="json")


def run_copy_job(
    *,
    client_account_id: int,
    keyword: str,
    usp: str,
    trigger: str,
    platform: AdPlatform,
) -> dict[str, Any]:
    """Job copywriter: genereaza copy si il salveaza in coada HITL (``AdQueueItem``)."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        llm_client = CreativeFactory(config).llm()
        generator = AdCopyGenerator(llm_client)
        ad_copy = generator.generate_emotional_copy(
            usp, keyword, trigger, platform, objective=account.objective
        )

        item = AdQueueItem(
            client_account_id=client_account_id,
            platform=Platform(platform),
            target_keyword=keyword,
            emotion_trigger=trigger,
            product_usp=usp,
            ad_copy=ad_copy,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {"ad_queue_item_id": item.id, "ad_copy": ad_copy}


def run_creative_job(
    *,
    client_account_id: int,
    keyword: str,
    broll_path: str,
    trigger: str,
    usp: str | None,
    platform: AdPlatform,
) -> dict[str, Any]:
    """Job Modulul 5: genereaza voce + video si inregistreaza artefactul."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = CreativeFactory(config)
        result = generate_full_ad_creative(
            factory.llm(),
            factory.tts(),
            factory.video(),
            keyword=keyword,
            raw_broll_path=broll_path,
            emotion_trigger=trigger,
            product_usp=usp,
            platform=platform,
        )

        artifact = CreativeArtifact(
            client_account_id=client_account_id,
            platform=Platform(result.platform),
            keyword=keyword,
            wav_path=result.voiceover_path,
            mp4_path=result.mp4_path,
            duration_seconds=result.duration_seconds,
            manifest=result.manifest,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return {"creative_artifact_id": artifact.id, "mp4_path": result.mp4_path}


def _to_db_row(client_account_id: int, change: CliProposedChange) -> ProposedChange:
    """Converteste un :class:`~ppc_agent.guardrails.models.ProposedChange` (CLI,
    Pydantic simplu) intr-un rand DB ``pending`` — aceleasi campuri, aceeasi
    forma, doar persistat in loc de scris in ``proposed_changes_*.json``."""
    return ProposedChange(
        client_account_id=client_account_id,
        op=ChangeOp(change.op),
        resource=change.resource,
        resource_type=change.resource_type,
        before=change.before,
        after=change.after,
        projected_daily_spend=change.projected_daily_spend,
        rationale=change.rationale,
        source_module=change.source_module,
    )


def _guarded_row(
    client_account_id: int, guarded: GuardedChange, constraints: CouncilConstraints, now: datetime
) -> ProposedChange:
    """Randul DB al unei propuneri trecute prin garda consiliului: ``pending`` sau ``blocked``."""
    row = _to_db_row(client_account_id, guarded.change)
    block = constraints.money_veto
    if guarded.blocked is not None and block is not None:
        row.status = ChangeStatus.BLOCKED
        row.decided_at = now
        row.decided_by = DECIDED_BY
        row.error_message = guarded.blocked
        row.before = {**row.before, "council": council_context(block)}
    return row


def _council_constraints(session: Session, client_account_id: int) -> CouncilConstraints:
    """Restrictiile consiliului in noaptea asta: memoria (7 zile) + Tehnicianul de acum.

    Ce s-a ridicat (conditia de rediscutare, indeplinita in datele de azi) se invalideaza
    in memorie pe loc - intrarile ``lifted:`` - iar ce a pus CFO-ul de noapte (contul a
    recazut pe pierdere) se scrie ca decizia lui: le vede si consiliul din chat.
    """
    now = datetime.now(tz=UTC)
    memory = DbMemory(session)
    decisions = memory.decisions(client_account_id, now - timedelta(days=COUNCIL_MEMORY_DAYS))
    signals = DbTechnicalSignals(session).load(client_account_id)
    technical = evaluate_technical_health(client_account_id, signals, generated_at=now)
    finances = build_financial_snapshot(DbFinancialSignals(session).load(client_account_id))
    constraints = council_constraints(decisions, technical, signals, now=now, finances=finances)
    if constraints.lifted or constraints.imposed:
        memory.remember(client_account_id, [*constraints.lifted, *constraints.imposed])
    return constraints


def launch_block(
    session: Session, client_account_id: int, constraints: CouncilConstraints
) -> CouncilBlock | None:
    """Ce opreste o lansare NOUA - mai putin decat ce opreste cresterea bugetului.

    Veto-ul Tehnicianului (tracking picat, site lent) o opreste mereu. Restrictia CFO-ului,
    doar cand contul pierde bani dovedit (``unprofitable``): fara conversii sau fara tinta,
    CFO-ul taie "cresterea bugetului", dar o prima campanie, in plafonul zilnic, e chiar
    felul in care se strang datele - altfel un client nou n-ar putea lansa niciodata
    (restrictia se ridica doar pe un cont rentabil). Rezerva lui ramane in aviz.
    """
    block = constraints.growth_block
    if block is None or block.role != "cfo":
        return block
    finances = build_financial_snapshot(DbFinancialSignals(session).load(client_account_id))
    return block if finances.status == "unprofitable" else None


def _block_pending(
    session: Session, client_account_id: int, constraints: CouncilConstraints, now: datetime
) -> int:
    """Opreste propunerile inca in asteptare pe care restrictiile nu le mai permit.

    Orice restrictie: lansarile de campanii (cheltuiala noua). Veto-ul pe bani: si
    planurile de buget si consolidarile din noptile trecute, calculate pe conversii.
    Tranzitia e conditionata (``WHERE status = pending``), ca la aprobare: o propunere
    aprobata chiar acum de client nu e suprascrisa.
    """
    block = constraints.growth_block
    if block is None:
        return 0
    launches = launch_block(session, client_account_id, constraints)
    query = select(ProposedChange).where(
        ProposedChange.client_account_id == client_account_id,
        ProposedChange.status == ChangeStatus.PENDING,
    )
    pending = session.exec(query).all()
    blocked = 0
    for proposal in pending:
        money_based = proposal.source_module in MONEY_MODULES
        if proposal.op is ChangeOp.CREATE_CAMPAIGN:
            if launches is None:
                continue
            reason = launches
        elif money_based and constraints.money_veto is not None:
            reason = constraints.money_veto
        else:
            continue
        result = session.exec(
            update(ProposedChange)
            .where(
                col(ProposedChange.id) == proposal.id,
                col(ProposedChange.status) == ChangeStatus.PENDING,
            )
            .values(
                status=ChangeStatus.BLOCKED,
                decided_at=now,
                decided_by=DECIDED_BY,
                error_message=blocked_message(reason),
                before={**proposal.before, "council": council_context(reason)},
            )
        )
        blocked += result.rowcount
    session.commit()
    return blocked


#: Modulele care isi refac planul complet in fiecare noapte: o propunere de ieri din
#: ele, inca neaprobata, are cifre vechi. Aprobata dupa cea de azi, le-ar suprascrie.
NIGHTLY_MODULES = frozenset({"budget", "negatives", "meta_liquidity"})
SUPERSEDED_BY = "planul de noapte"


def _supersede(
    session: Session, client_account_id: int, modules: frozenset[str], now: datetime
) -> int:
    """Respinge propunerile inca in asteptare din ``modules``: planul nou le inlocuieste.

    Conditionat pe ``pending``, ca la aprobare: una aprobata chiar acum nu se atinge.
    """
    result = session.exec(
        update(ProposedChange)
        .where(
            col(ProposedChange.client_account_id) == client_account_id,
            col(ProposedChange.status) == ChangeStatus.PENDING,
            col(ProposedChange.source_module).in_(modules),
        )
        .values(
            status=ChangeStatus.REJECTED,
            decided_at=now,
            decided_by=SUPERSEDED_BY,
            error_message=(
                f"Înlocuită de planul din {now:%d.%m.%Y}: cifrele ei nu mai sunt la zi."
            ),
        )
    )
    return result.rowcount


def _consult_queen(session: Session, client_account_id: int) -> dict[str, Any]:
    """Directiva Reginei, transformata in rescrieri in asteptare.

    Regina doar sfatuieste: daca pica (ex. Search Console nu raspunde), PPC-ul
    merge mai departe cu Kelly/Thompson, iar eroarea ramane in rezultat.
    """
    try:
        return apply_brand_directive(session, client_account_id)
    except Exception as exc:
        session.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_propose_job(*, client_account_id: int) -> dict[str, Any]:
    """Job Modulul 4: genereaza propuneri (buget + negative + lichiditate Meta) si
    le persista ca randuri ``ProposedChange`` ``pending`` — echivalentul
    server-side, DB-backed, al comenzii CLI ``propose`` (acolo: fisier JSON +
    ``ApprovalGate``; aici: randuri DB, acelasi camp cu camp).

    Inainte de Kelly/Thompson, cere directiva Reginei (``jobs/brand_alignment.py``):
    reclamele care nu vorbesc clientului ideal primesc propuneri de rescriere
    (``UPDATE``), oricat de stabil ar parea CPA-ul lor.

    Dupa Kelly/Thompson, garda consiliului (``services/council_guard.py``): un veto
    al Tehnicianului sau o taietura a CFO-ului (memoria consiliului, 7 zile, plus
    raportul tehnic de acum) suprascrie algoritmii. Ce opreste se scrie tot in DB,
    ca ``blocked``, cu motivul in ``error_message`` - clientul vede de ce.

    Nimic nu se executa - propunerile raman ``pending`` pana la o cerere
    explicita ``POST /api/v1/proposals/{id}/execute`` cu ``confirm=true``
    (poarta HITL neschimbata, vezi ``routers/proposals.py``).

    Raises:
        ClientNotFoundError: Clientul nu exista.
        SpendLimitExceeded: Cheltuiala zilnica totala propusa ar depasi
            limita clientului - nimic din planul de buget nu se scrie (ca la
            ``ApprovalGate.flush()``). Rescrierile Reginei, care nu muta bani,
            sunt deja salvate.
    """
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        # Oprirea de urgenta (``services/emergency_stop.py``): noaptea nu propune nimic.
        stop = session.exec(
            select(EmergencyStop).where(col(EmergencyStop.resumed_at).is_(None))
        ).first()
        if stop is not None:
            return {"client_account_id": client_account_id, "skipped": "oprire de urgență"}
        config = _app_config_for(account)
        factory = ProviderFactory(config)

        brand_alignment = _consult_queen(session, client_account_id)
        constraints = _council_constraints(session, client_account_id)

        ingestion = run_ingestion(factory, account.target_domain, config)
        decision = run_plan(factory, config)
        alignment = run_alignment(factory, config, ingestion.page_context)

        changes = build_proposed_changes(
            budget_plan=decision.budget_plan,
            negatives=ingestion.negative_keywords,
            liquidity=alignment.liquidity_plan,
            kelly=decision.kelly,
            ad_sets=alignment.ad_sets,
        )
        guarded = guard_changes(changes, constraints, spend_cap=config.budget.max_daily_spend)
        allowed = [item for item in guarded if item.blocked is None]

        total = sum((item.change.projected_daily_spend for item in allowed), Decimal("0"))
        AbsoluteSpendLimiter(decision.kelly.sized_daily_cap).check(
            sum((item.change.spend_against_cap for item in allowed), Decimal("0"))
        )

        now = datetime.now(tz=UTC)
        rows = [_guarded_row(client_account_id, item, constraints, now) for item in guarded]
        superseded = _supersede(session, client_account_id, NIGHTLY_MODULES, now)
        session.add_all(rows)
        session.commit()
        result: dict[str, Any] = {
            "created": len(allowed),
            "superseded": superseded,
            "total_projected_daily_spend": str(total),
            "brand_alignment": brand_alignment,
        }
        lifted = [memory_line(entry, now) for entry in constraints.lifted]
        for line in lifted:
            logger.info("[Consiliu] client %s: restricție ridicată. %s", client_account_id, line)
        imposed = [memory_line(entry, now) for entry in constraints.imposed]
        if constraints.active or lifted:
            council: dict[str, Any] = {
                "note": constraints.note(),
                "blocked": len(guarded) - len(allowed),
                "capped": sum(1 for item in guarded if item.capped_from is not None),
                "blocked_pending": _block_pending(session, client_account_id, constraints, now),
                "lifted": lifted,
                "imposed": imposed,
            }
            if constraints.active:
                logger.warning(
                    "[Consiliu] client %s: %d propuneri oprite, %d plafonate, %d în așteptare "
                    "oprite. %s",
                    client_account_id,
                    council["blocked"],
                    council["capped"],
                    council["blocked_pending"],
                    council["note"],
                )
            result["council"] = council
        return result


def run_fatigue_check_job(*, client_account_id: int) -> dict[str, Any]:
    """Job: evalueaza monitorul de oboseala pentru toate ``AdPerformanceRecord``
    ale clientului si persista verdictele de oprire ca ``ProposedChange``
    ``pending`` — echivalentul server-side al ``check-fatigue`` (acolo: JSON de
    operator; aici: randurile deja persistate de pipeline-ul de conversii,
    convertite prin ``tracking.pipeline.to_ad_performance_state``).
    """
    with Session(get_engine()) as session:
        _require_client(session, client_account_id)
        records = session.exec(
            select(AdPerformanceRecord).where(
                AdPerformanceRecord.client_account_id == client_account_id
            )
        ).all()
        states = [to_ad_performance_state(record) for record in records]

        now = datetime.now(tz=UTC)
        changes = build_fatigue_changes(states, now)
        rows = [_to_db_row(client_account_id, change) for change in changes]
        superseded = _supersede(session, client_account_id, frozenset({"fatigue_monitor"}), now)
        session.add_all(rows)
        session.commit()
        return {"evaluated": len(states), "created": len(rows), "superseded": superseded}


def run_metrics_sync_job(*, client_account_id: int) -> dict[str, Any]:
    """Sincronizeaza ``spend``/``clicks`` din providerul activ (mock sau live) in
    ``AdPerformanceRecord``, pentru randurile al caror ``ad_id`` se regaseste in
    ``campaign_performance()``.

    Scop deliberat limitat: NU atinge ``conversions``/``revenue`` (proprietatea
    pipeline-ului de urmarire a conversiilor, vezi ``tracking/pipeline.py``) si
    NU poate popula ``impressions``/``ctr``/frecventa/liniile de baza CTR-CPA pe
    care Gate B/C din Fatigue Monitor le folosesc - ``GoogleAdsProvider``,
    ``TikTokAdsProvider`` si ``MetaMarketingProvider`` nu expun inca acele
    coloane (``campaign_performance()`` intoarce doar
    ``arm_id/name/clicks/conversions/cost/revenue``). Verdictele care depind de
    ele raman la fel de "oarbe" ca inainte de acest job - gap documentat, nu
    ascuns. NU creeaza randuri noi (doar actualizeaza randuri deja existente) -
    crearea ramane in sarcina pipeline-ului de conversii, care are contextul
    (target_cpa, platforma) necesar unui rand nou.

    Tot aici se inlocuieste :class:`PlatformArmSnapshot` al clientului: ce a citit
    agentul din platforme in noaptea asta, pentru CFO. Doar in ``live``: in ``mock``
    cifrele sunt inventate, iar restrictiile CFO-ului raman 7 zile in memoria
    consiliului - una ridicata pe date fictive ar ajunge in pilotul real. In ``mock``
    rezumatul se goleste, iar CFO-ul ramane pe conversiile primite prin webhook.
    """
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = ProviderFactory(config)

        google_id = account.google_ads_customer_id or _MOCK_CUSTOMER_ID
        tiktok_id = account.tiktok_advertiser_id or _MOCK_ADVERTISER_ID
        meta_id = account.meta_ad_account_id or _MOCK_AD_ACCOUNT_ID
        arms = [
            arm
            for platform, read, account_id in (
                ("google_ads", factory.google_ads, google_id),
                ("tiktok_ads", factory.tiktok_ads, tiktok_id),
                ("meta_ads", factory.meta, meta_id),
            )
            if factory.configured(platform)
            for arm in arms_from_performance(
                read().campaign_performance(account_id), platform=platform
            )
        ]
        performance_by_arm = {arm.arm_id: (arm.cost, arm.clicks) for arm in arms}
        now = datetime.now(tz=UTC)
        session.exec(
            delete(PlatformArmSnapshot).where(
                col(PlatformArmSnapshot.client_account_id) == client_account_id
            )
        )
        arms_for_cfo = arms if factory.mode is ProviderMode.LIVE else []
        session.add_all(
            PlatformArmSnapshot(
                client_account_id=client_account_id,
                platform=arm.platform,
                arm_id=arm.arm_id,
                name=arm.name,
                clicks=arm.clicks,
                conversions=arm.conversions,
                cost=arm.cost,
                revenue=arm.revenue,
                synced_at=now,
            )
            for arm in arms_for_cfo
        )

        records = session.exec(
            select(AdPerformanceRecord).where(
                AdPerformanceRecord.client_account_id == client_account_id
            )
        ).all()

        updated = 0
        for record in records:
            source = performance_by_arm.get(record.ad_id)
            if source is None:
                continue
            record.spend, record.clicks = source
            record.updated_at = now
            session.add(record)
            updated += 1
        session.commit()
        return {"checked": len(records), "updated": updated, "platform_arms": len(arms_for_cfo)}


def list_client_account_ids() -> list[int]:
    """Id-urile tuturor clientilor - lista pe care o imparte mentenanta de noapte."""
    with Session(get_engine()) as session:
        ids = session.exec(select(ClientAccount.id)).all()
    return [client_id for client_id in ids if client_id is not None]


#: PageSpeed ruleaza Lighthouse pe pagina reala: pe mobil, de obicei 10-30 s.
PAGESPEED_TIMEOUT_SECONDS = 60.0
#: Lighthouse e un test sintetic, cu zgomot de la o rulare la alta: 3 rulari, mediana.
PAGESPEED_RUNS = 3
_LAB_METRICS = ("performance_score", "lcp_ms", "cls", "tbt_ms")
_FIELD_METRICS = ("field_lcp_ms", "field_cls", "field_inp_ms")

PageSpeedMeasure = Callable[[str], dict[str, Any] | None]


def median_pagespeed(runs: Sequence[dict[str, Any] | None]) -> dict[str, Any] | None:
    """Mediana fiecarei metrici de laborator peste rularile reusite; ``None`` fara niciuna.

    Datele de teren (CrUX) sunt aceleasi la fiecare rulare - se ia prima valoare.
    """
    done = [run for run in runs if run is not None]
    if not done:
        return None
    combined: dict[str, Any] = {"runs": len(done)}
    for metric in _LAB_METRICS:
        values = [run[metric] for run in done if isinstance(run.get(metric), int | float)]
        combined[metric] = statistics.median(values) if values else None
    for metric in _FIELD_METRICS:
        combined[metric] = next((run[metric] for run in done if run.get(metric) is not None), None)
    return combined


def measure_mobile_speed(url: str) -> dict[str, Any] | None:
    """Masuratoarea agentului SEO/GEO: PageSpeed Insights, mobil, 3 rulari in paralel, mediana.

    ``None`` cand pica toate (cota, timeout, site cazut) - vezi
    ``seo_geo_agent/external_data.py``. Cheia API e optionala
    (``SEOGEO_PAGESPEED_API_KEY``); fara ea, cota Google e mica, dar ajunge
    pentru o masuratoare pe client pe noapte.
    """

    async def _runs() -> list[dict[str, Any] | None]:
        key = get_seo_geo_settings().pagespeed_api_key
        return list(
            await asyncio.gather(
                *(
                    fetch_pagespeed_insights(
                        url, api_key=key, strategy="mobile", timeout=PAGESPEED_TIMEOUT_SECONDS
                    )
                    for _ in range(PAGESPEED_RUNS)
                )
            )
        )

    return median_pagespeed(asyncio.run(_runs()))


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def run_speed_check_job(
    *, client_account_id: int, measure: PageSpeedMeasure | None = None
) -> dict[str, Any]:
    """Viteza pe mobil a site-ului clientului, salvata pentru Tehnician.

    Un rand nou ``SiteSpeedSample`` la fiecare masuratoare reusita (istoric, nu
    suprascriere). Fara domeniu in Setari nu are ce masura; o masuratoare
    esuata nu scrie nimic - Tehnicianul ramane pe ultima buna, cat timp nu e
    prea veche, si nu inventeaza o stare.
    """
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        if not account.target_domain.strip():
            return {"measured": False, "reason": "fara domeniu in Setari"}
        url = site_url(account.target_domain)
        # ``measure_mobile_speed`` citit la apel, nu legat la import: testele il
        # inlocuiesc (``tests_server/conftest.py``), ca sa nu iasa spre Google.
        result = (measure or measure_mobile_speed)(url)
        if result is None:
            return {"measured": False, "url": url, "reason": "PageSpeed nu a raspuns"}
        sample = SiteSpeedSample(
            client_account_id=client_account_id,
            url=url,
            performance_score=_optional_int(result.get("performance_score")),
            lcp_ms=_optional_int(result.get("lcp_ms")),
            layout_shift=_optional_float(result.get("cls")),
            tbt_ms=_optional_int(result.get("tbt_ms")),
            runs=_optional_int(result.get("runs")) or 1,
            field_lcp_ms=_optional_int(result.get("field_lcp_ms")),
            field_cls=_optional_float(result.get("field_cls")),
            field_inp_ms=_optional_int(result.get("field_inp_ms")),
        )
        session.add(sample)
        session.commit()
        return {
            "measured": True,
            "url": url,
            "performance_score": sample.performance_score,
            "lcp_ms": sample.lcp_ms,
        }


#: Auditul de noapte: destul cat sa prinda paginile care conteaza (acasa, servicii,
#: contact), fara sa tina mentenanta clientului pe loc (limita ei e 600 s).
SITE_AUDIT_MAX_PAGES = 25
SITE_AUDIT_TIME_BUDGET_SECONDS = 120.0
#: Cate tipuri de probleme se pastreaza pentru Tehnician - cele mai grave.
SITE_AUDIT_TOP_ISSUES = 5
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

SiteAuditRun = Callable[[str, str], AuditResult | None]


def run_site_audit(url: str, brand: str) -> AuditResult | None:
    """Motorul de audit al agentului SEO/GEO, pe site-ul clientului; ``None`` = tinta refuzata.

    Aceeasi validare ca ``POST /api/v1/seo-geo/audit``: o adresa interna sau privata
    nu se crawleaza (SSRF), nici cand vine din Setarile clientului.
    """

    async def _audit() -> AuditResult | None:
        try:
            start_url = await normalize_and_validate_start_url(url)
        except (ValueError, CrawlTargetBlockedError):
            return None
        config = AuditConfig(
            max_pages=SITE_AUDIT_MAX_PAGES,
            time_budget_seconds=SITE_AUDIT_TIME_BUDGET_SECONDS,
            brand=brand,
        )
        return await run_audit(start_url, config)

    return asyncio.run(_audit())


def _first_sentence(text: str, limit: int = 220) -> str:
    sentence = text.split(". ")[0].strip().rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rsplit(" ", 1)[0] + "…"


def audit_snapshot(client_account_id: int, result: AuditResult) -> SiteAuditSnapshot:
    """Ce ramane din raportul complet: scorurile, numaratoarea si problemele cele mai grave."""
    pages: dict[str, set[str]] = {}
    for issue in result.issues:
        pages.setdefault(issue.issue_type, set()).add(issue.page_url)
    kinds = [
        (issue_type, AUDIT_ISSUE_TYPES[issue_type], len(urls))
        for issue_type, urls in pages.items()
        if issue_type in AUDIT_ISSUE_TYPES
    ]
    kinds.sort(key=lambda kind: (_SEVERITY_RANK[kind[1].severity], -kind[2], kind[0]))
    counts = {severity: 0 for severity in _SEVERITY_RANK}
    for _, descriptor, _ in kinds:
        counts[descriptor.severity] += 1
    scores = result.scores
    return SiteAuditSnapshot(
        client_account_id=client_account_id,
        url=result.start_url,
        audited_at=result.finished_at,
        pages_crawled=len(result.pages),
        completed=result.completed,
        seo_score=scores["seo"].score if "seo" in scores else None,
        geo_score=scores["geo"].score if "geo" in scores else None,
        critical_issues=counts["critical"],
        warning_issues=counts["warning"],
        info_issues=counts["info"],
        top_issues=[
            {
                "type": issue_type,
                "title": descriptor.title,
                "severity": descriptor.severity,
                "pages": affected,
                "fix": _first_sentence(descriptor.how_to_fix),
            }
            for issue_type, descriptor, affected in kinds[:SITE_AUDIT_TOP_ISSUES]
        ],
    )


def run_site_audit_job(
    *, client_account_id: int, audit: SiteAuditRun | None = None
) -> dict[str, Any]:
    """Auditul tehnic SEO/GEO al site-ului clientului, rezumat pentru Tehnician.

    Un rand nou ``SiteAuditSnapshot`` la fiecare audit (istoric). Fara domeniu in
    Setari nu are ce audita; un audit refuzat (adresa interna) nu scrie nimic.
    """
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        if not account.target_domain.strip():
            return {"audited": False, "reason": "fara domeniu in Setari"}
        url = site_url(account.target_domain)
        # ``run_site_audit`` citit la apel: testele il inlocuiesc (``conftest.py``).
        result = (audit or run_site_audit)(url, account.brand_name)
        if result is None:
            return {"audited": False, "url": url, "reason": "adresa refuzata de politica de crawl"}
        snapshot = audit_snapshot(client_account_id, result)
        session.add(snapshot)
        session.commit()
        return {
            "audited": True,
            "url": snapshot.url,
            "pages": snapshot.pages_crawled,
            "critical_issues": snapshot.critical_issues,
        }


def run_client_maintenance_job(*, client_account_id: int) -> dict[str, Any]:
    """Mentenanta de noapte pentru UN client: sincronizare, viteza, audit, E2E, propuneri, oboseala.

    Micro-jobul pe care cron-ul ARQ il programeaza pentru fiecare client
    (``jobs/worker.py``), cu timeout-ul lui: un client lent sau o platforma
    care nu raspunde nu mai tine pe loc restul conturilor. Pasii raman izolati
    intre ei - un pas care pica (ex. ``SpendLimitExceeded`` la propose) isi
    raporteaza eroarea, iar urmatorul ruleaza oricum. Viteza si testul E2E ruleaza
    INAINTE de propuneri: garda consiliului judeca pe dovezile din noaptea asta
    (un pixel picat azi opreste bugetele azi; unul reparat azi le deblocheaza azi).
    """
    result: dict[str, Any] = {}
    for step_name, job in (
        ("sync", run_metrics_sync_job),
        ("speed_check", run_speed_check_job),
        ("site_audit", run_site_audit_job),
        ("tracking_contract", run_tracking_contract_job),
        ("propose", run_propose_job),
        ("fatigue_check", run_fatigue_check_job),
    ):
        try:
            result[step_name] = job(client_account_id=client_account_id)
        except Exception as exc:
            result[step_name] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def run_daily_maintenance_job() -> dict[str, Any]:
    """Mentenanta de noapte pentru TOTI clientii, pe rand, in acelasi proces.

    Varianta fara Redis (coada inline, CLI, teste). Cu un worker ARQ real,
    cron-ul NU o foloseste: face fan-out, cate un :func:`run_client_maintenance_job`
    per client (vezi ``jobs/worker.py``). Un client care esueaza nu ii opreste
    pe ceilalti - eroarea lui se raporteaza in rezultat, nu se propaga.
    """
    client_ids = list_client_account_ids()
    per_client = {
        str(client_id): run_client_maintenance_job(client_account_id=client_id)
        for client_id in client_ids
    }
    return {"clients_processed": len(client_ids), "results": per_client}
