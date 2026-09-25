"""Task-urile efective: wrapper-e subtiri peste pipeline-urile pure din ``ppc_agent``.

Fiecare functie isi deschide propria sesiune DB (nu primeste una de la apelant)
si accepta doar argumente serializabile — functioneaza identic fie apelata
inline (``InlineJobQueue``, Faza E), fie intr-un proces worker ARQ separat
(Faza F), unde nu exista nicio sesiune HTTP de mostenit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlmodel import Session, select

from ppc_agent.alignment.pipeline import run_alignment
from ppc_agent.config import AppConfig, BudgetConfig, Settings
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.creative.creative_pipeline import generate_full_ad_creative
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.decision.pipeline import run_plan
from ppc_agent.guardrails.models import ProposedChange as CliProposedChange
from ppc_agent.guardrails.pipeline import build_fatigue_changes, build_proposed_changes
from ppc_agent.guardrails.spend_limiter import AbsoluteSpendLimiter
from ppc_agent.ingestion.pipeline import run_ingestion
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent_server.db import get_engine
from ppc_agent_server.jobs.brand_alignment import apply_brand_directive
from ppc_agent_server.models import (
    AdPerformanceRecord,
    AdQueueItem,
    ChangeOp,
    ClientAccount,
    CreativeArtifact,
    Platform,
    ProposedChange,
    SiteSpeedSample,
)
from ppc_agent_server.security import decrypt_secret
from ppc_agent_server.tracking.pipeline import to_ad_performance_state
from seo_geo_agent.external_data import fetch_pagespeed_insights
from seo_geo_agent.settings import get_seo_geo_settings

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
        config = _app_config_for(account)
        factory = ProviderFactory(config)

        brand_alignment = _consult_queen(session, client_account_id)

        ingestion = run_ingestion(factory, account.target_domain, config)
        decision = run_plan(factory, config)
        alignment = run_alignment(factory, config, ingestion.page_context)

        changes = build_proposed_changes(
            budget_plan=decision.budget_plan,
            negatives=ingestion.negative_keywords,
            liquidity=alignment.liquidity_plan,
            kelly=decision.kelly,
        )

        total = sum((change.projected_daily_spend for change in changes), Decimal("0"))
        AbsoluteSpendLimiter(decision.kelly.sized_daily_cap).check(total)

        rows = [_to_db_row(client_account_id, change) for change in changes]
        session.add_all(rows)
        session.commit()
        return {
            "created": len(rows),
            "total_projected_daily_spend": str(total),
            "brand_alignment": brand_alignment,
        }


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

        changes = build_fatigue_changes(states, datetime.now(tz=UTC))
        rows = [_to_db_row(client_account_id, change) for change in changes]
        session.add_all(rows)
        session.commit()
        return {"evaluated": len(states), "created": len(rows)}


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
    """
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = ProviderFactory(config)

        performance_by_arm: dict[str, tuple[float, int]] = {}
        google_id = account.google_ads_customer_id or _MOCK_CUSTOMER_ID
        tiktok_id = account.tiktok_advertiser_id or _MOCK_ADVERTISER_ID
        meta_id = account.meta_ad_account_id or _MOCK_AD_ACCOUNT_ID
        for frame in (
            factory.google_ads().campaign_performance(google_id),
            factory.tiktok_ads().campaign_performance(tiktok_id),
            factory.meta().campaign_performance(meta_id),
        ):
            for row in frame.to_dict(orient="records"):
                performance_by_arm[str(row["arm_id"])] = (
                    float(row["cost"]),
                    int(row["clicks"]),
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
            cost, clicks = source
            record.spend = Decimal(str(cost))
            record.clicks = clicks
            record.updated_at = datetime.now(tz=UTC)
            session.add(record)
            updated += 1
        session.commit()
        return {"checked": len(records), "updated": updated}


def list_client_account_ids() -> list[int]:
    """Id-urile tuturor clientilor - lista pe care o imparte mentenanta de noapte."""
    with Session(get_engine()) as session:
        ids = session.exec(select(ClientAccount.id)).all()
    return [client_id for client_id in ids if client_id is not None]


#: PageSpeed ruleaza Lighthouse pe pagina reala: pe mobil, de obicei 10-30 s.
PAGESPEED_TIMEOUT_SECONDS = 60.0

PageSpeedMeasure = Callable[[str], dict[str, Any] | None]


def measure_mobile_speed(url: str) -> dict[str, Any] | None:
    """Masuratoarea agentului SEO/GEO: PageSpeed Insights, strategia mobil.

    ``None`` la orice esec (cota, timeout, site cazut) - vezi
    ``seo_geo_agent/external_data.py``. Cheia API e optionala
    (``SEOGEO_PAGESPEED_API_KEY``); fara ea, cota Google e mica, dar ajunge
    pentru o masuratoare pe client pe noapte.
    """
    return asyncio.run(
        fetch_pagespeed_insights(
            url,
            api_key=get_seo_geo_settings().pagespeed_api_key,
            strategy="mobile",
            timeout=PAGESPEED_TIMEOUT_SECONDS,
        )
    )


def _site_url(target_domain: str) -> str:
    """``https://exemplu.ro/`` din domeniul din Setari (salvat ca origine sau, vechi, ca nume)."""
    origin = target_domain.strip().rstrip("/")
    return f"{origin if '://' in origin else f'https://{origin}'}/"


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
        url = _site_url(account.target_domain)
        # ``measure_mobile_speed`` citit la apel, nu legat la import: testele il
        # inlocuiesc (``tests_server/conftest.py``), ca sa nu iasa spre Google.
        result = (measure or measure_mobile_speed)(url)
        if result is None:
            return {"measured": False, "url": url, "reason": "PageSpeed nu a raspuns"}
        layout_shift = result.get("cls")
        sample = SiteSpeedSample(
            client_account_id=client_account_id,
            url=url,
            performance_score=_optional_int(result.get("performance_score")),
            lcp_ms=_optional_int(result.get("lcp_ms")),
            layout_shift=_optional_float(layout_shift),
            tbt_ms=_optional_int(result.get("tbt_ms")),
        )
        session.add(sample)
        session.commit()
        return {
            "measured": True,
            "url": url,
            "performance_score": sample.performance_score,
            "lcp_ms": sample.lcp_ms,
        }


def run_client_maintenance_job(*, client_account_id: int) -> dict[str, Any]:
    """Mentenanta de noapte pentru UN client: sincronizare, propuneri, oboseala, viteza.

    Micro-jobul pe care cron-ul ARQ il programeaza pentru fiecare client
    (``jobs/worker.py``), cu timeout-ul lui: un client lent sau o platforma
    care nu raspunde nu mai tine pe loc restul conturilor. Pasii raman izolati
    intre ei - un pas care pica (ex. ``SpendLimitExceeded`` la propose) isi
    raporteaza eroarea, iar urmatorul ruleaza oricum.
    """
    result: dict[str, Any] = {}
    for step_name, job in (
        ("sync", run_metrics_sync_job),
        ("propose", run_propose_job),
        ("fatigue_check", run_fatigue_check_job),
        ("speed_check", run_speed_check_job),
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
