"""Endpoint-urile agentului SEO+GEO.

Doua familii, deliberat separate:

- ``POST /analyze`` - analiza prin LLM: o parere argumentata despre domeniu.
- ``POST /audit`` + ``GET /audit/{id}`` + ``GET /audit/{id}/results`` - auditul
  determinist (``seo_geo_agent/audit/``). Trei endpoint-uri, nu unul, din
  acelasi motiv ca in ``every-app/open-seo`` (start / status / results): un
  crawl de zeci de pagini nu incape intr-un request sincron fara ca UI-ul sa
  para inghetat, iar progresul e informatie utila, nu zgomot.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from seo_geo_agent.audit.service import AuditConfig, AuditProgress, AuditResult, run_audit
from seo_geo_agent.audit.store import AuditRecord, AuditStore, TooManyAuditsError, audit_store
from seo_geo_agent.audit.url_policy import CrawlTargetBlockedError, normalize_and_validate_start_url
from seo_geo_agent.auth import get_current_client_id
from seo_geo_agent.engine import SeoGeoAnalyzer
from seo_geo_agent.errors import CrawlTargetError
from seo_geo_agent.external_data import fetch_page_content, fetch_pagespeed_insights
from seo_geo_agent.llm import BaseLLMClient, LiveLLMClient, MockLLMClient
from seo_geo_agent.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    AuditRequest,
    AuditResultsResponse,
    AuditStartedResponse,
    AuditStatusResponse,
)
from seo_geo_agent.settings import ProviderMode, get_seo_geo_settings

logger = logging.getLogger("seo_geo_agent.router")

router = APIRouter(prefix="/api/v1/seo-geo", tags=["seo-geo"])

AutoFetcher = Callable[[str], Awaitable[str]]
AuditRunner = Callable[[str, AuditConfig, Callable[[AuditProgress], None]], Awaitable[AuditResult]]

#: Referinte tari catre task-urile in derulare. Fara ele, ``asyncio`` are voie
#: sa colecteze un task caruia nimeni nu-i tine de urma, iar auditul s-ar opri
#: in mijloc, fara eroare.
_running_tasks: set[asyncio.Task[None]] = set()


def _build_llm_client() -> BaseLLMClient:
    settings = get_seo_geo_settings()
    if settings.provider_mode is ProviderMode.MOCK:
        return MockLLMClient()
    num_gpu = int(settings.llm_num_gpu) if settings.llm_num_gpu.strip() else None
    return LiveLLMClient(settings.llm_model, settings.llm_endpoint, num_gpu=num_gpu)


async def _fetch_real_data_report(domain: str) -> str:
    """Inlocuieste rapoartele manuale (Ahrefs/Semrush/PageSpeed Insights deschise
    separat) cu date REALE, preluate automat pentru ``domain`` - vezi
    ``external_data.py``. Esec partial sau total (retea, rate-limit, domeniu
    inaccesibil) -> sectiunea respectiva se omite, niciodata eroare catre client
    (acelasi contract failsafe ca fiecare functie din ``external_data.py``).
    """
    url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    settings = get_seo_geo_settings()
    sections: list[str] = []

    pagespeed = await fetch_pagespeed_insights(url, api_key=settings.pagespeed_api_key)
    if pagespeed is not None:
        sections.append(
            "Date reale PageSpeed Insights (preluate automat, nu introduse de client):\n"
            f"- scor performanta: {pagespeed['performance_score']}/100\n"
            f"- Largest Contentful Paint: {pagespeed['largest_contentful_paint']}\n"
            f"- Cumulative Layout Shift: {pagespeed['cumulative_layout_shift']}\n"
            f"- Total Blocking Time: {pagespeed['total_blocking_time']}"
        )

    content = await fetch_page_content(url)
    if content is not None:
        sections.append(
            "Continutul paginii principale (preluat automat, nu introdus de client):\n"
            f"- titlu: {content.get('title') or 'lipsa'}\n"
            f"- descriere: {content.get('description') or 'lipsa'}\n"
            f"- limba detectata: {content.get('lang') or 'necunoscuta'}"
        )

    return "\n\n".join(sections)


def _get_auto_fetcher() -> AutoFetcher:
    """Dependinta FastAPI separata (nu ``_fetch_real_data_report`` apelata direct)
    - testele o inlocuiesc cu un fals fara retea, acelasi principiu ca
    ``_build_llm_client`` (vezi ``tests_seo_geo/conftest.py``)."""
    return _fetch_real_data_report


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    payload: AnalysisRequest,
    llm_client: Annotated[BaseLLMClient, Depends(_build_llm_client)],
    auto_fetch: Annotated[AutoFetcher, Depends(_get_auto_fetcher)],
    _client_id: Annotated[int, Depends(get_current_client_id)],
) -> AnalysisResponse:
    """Analizeaza un domeniu; returneaza scoruri + sugestii.

    ``client_reports`` e OPTIONAL: agentul preia singur date reale (PageSpeed
    Insights + continutul paginii - vezi ``_fetch_real_data_report``) inainte
    sa intrebe LLM-ul, inlocuind nevoia de a deschide manual Semrush/Ahrefs/
    PageSpeed Insights. Daca clientul scrie si el ceva, cele doua surse se
    combina (ambele ajung in prompt) - niciuna nu o exclude pe cealalta.
    Necesita autentificare (acelasi token de client folosit pe restul site-ului)
    - e un feature premium, nu un endpoint public. ``llm_client``/``auto_fetch``
    sunt dependinte (nu apelate direct) ca testele sa poata injecta variante
    false prin ``app.dependency_overrides``.
    """
    auto_report = await auto_fetch(payload.domain)
    manual_report = payload.client_reports.strip()
    combined = "\n\n".join(part for part in (manual_report, auto_report) if part)
    if not combined:
        raise HTTPException(
            status_code=422,
            detail=(
                "Nu am nicio informatie de analizat: completeaza campul de rapoarte "
                "sau verifica daca domeniul e corect si accesibil public."
            ),
        )

    merged_payload = payload.model_copy(update={"client_reports": combined})
    return SeoGeoAnalyzer(llm_client).analyze(merged_payload)


# ---------------------------------------------------------------------------
# Audit determinist
# ---------------------------------------------------------------------------


def _get_audit_runner() -> AuditRunner:
    """Dependinta FastAPI pentru motorul de audit.

    Exista din acelasi motiv ca ``_build_llm_client``/``_get_auto_fetcher``:
    testele o inlocuiesc cu un motor fals, ca suita sa ramana 100% fara retea.
    """
    return run_audit


def _get_audit_store() -> AuditStore:
    """Registrul auditurilor. Injectabil, ca testele sa porneasca de la unul gol."""
    return audit_store


async def _execute_audit(
    record: AuditRecord, start_url: str, config: AuditConfig, runner: AuditRunner, store: AuditStore
) -> None:
    """Ruleaza auditul in fundal si scrie rezultatul (sau eroarea) in registru.

    Prinde ``Exception`` deliberat: un audit cazut trebuie sa lase auditul
    marcat "failed" cu un mesaj, nu un task mort in tacere pe care clientul il
    interogheaza la nesfarsit.
    """
    record.progress = AuditProgress(crawled=0, queued=0, max_pages=config.max_pages)

    def on_progress(progress: AuditProgress) -> None:
        record.progress = progress

    try:
        result = await runner(start_url, config, on_progress)
    except Exception as exc:
        logger.exception("audit esuat pentru %s", start_url)
        store.mark_failed(record, f"Auditul nu s-a putut finaliza: {exc}")
        return
    store.mark_completed(record, result)


@router.post("/audit", response_model=AuditStartedResponse, status_code=202)
async def start_audit(
    payload: AuditRequest,
    client_id: Annotated[int, Depends(get_current_client_id)],
    runner: Annotated[AuditRunner, Depends(_get_audit_runner)],
    store: Annotated[AuditStore, Depends(_get_audit_store)],
) -> AuditStartedResponse:
    """Porneste un audit si intoarce imediat id-ul lui (202, nu raportul).

    URL-ul de start e validat SINCRON, inainte de a porni ceva: un domeniu
    gresit sau o tinta interna trebuie sa dea eroare in cererea asta, nu peste
    un minut, intr-un raport.
    """
    try:
        start_url = await normalize_and_validate_start_url(payload.domain)
    except CrawlTargetBlockedError as exc:
        raise CrawlTargetError(
            f"Nu pot audita '{exc}': e o adresa interna sau privata, nu un site public."
        ) from exc
    except ValueError as exc:
        raise CrawlTargetError(
            "Domeniul nu pare valid. Scrie-l ca 'exemplu.ro' sau 'https://exemplu.ro'."
        ) from exc

    try:
        record = store.create(client_id, payload.domain)
    except TooManyAuditsError as exc:
        raise HTTPException(
            status_code=429,
            detail="Ai deja un audit in derulare. Asteapta sa se termine si incearca din nou.",
        ) from exc

    settings = get_seo_geo_settings()
    config = AuditConfig(
        max_pages=min(payload.max_pages, settings.audit_max_pages),
        time_budget_seconds=settings.audit_time_budget_seconds,
        brand=payload.brand,
    )
    task = asyncio.create_task(_execute_audit(record, start_url, config, runner, store))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)

    return AuditStartedResponse(
        audit_id=record.audit_id, status=record.status, domain=record.domain
    )


@router.get("/audit/{audit_id}", response_model=AuditStatusResponse)
def get_audit_status(
    audit_id: str,
    client_id: Annotated[int, Depends(get_current_client_id)],
    store: Annotated[AuditStore, Depends(_get_audit_store)],
) -> AuditStatusResponse:
    """Starea si progresul unui audit. Se interogheaza pana cand nu mai e "running"."""
    record = store.get(client_id, audit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Auditul nu exista sau a expirat.")
    return AuditStatusResponse.from_record(record)


@router.get("/audit/{audit_id}/results", response_model=AuditResultsResponse)
def get_audit_results(
    audit_id: str,
    client_id: Annotated[int, Depends(get_current_client_id)],
    store: Annotated[AuditStore, Depends(_get_audit_store)],
) -> AuditResultsResponse:
    """Raportul complet al unui audit terminat."""
    record = store.get(client_id, audit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Auditul nu exista sau a expirat.")
    if record.status == "failed":
        raise HTTPException(status_code=502, detail=record.error or "Auditul a esuat.")
    if record.result is None:
        raise HTTPException(status_code=409, detail="Auditul inca ruleaza.")
    return AuditResultsResponse.from_result(record.audit_id, record.domain, record.result)
