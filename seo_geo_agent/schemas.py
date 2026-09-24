"""Structuri de date tipizate pentru seo_geo_agent.

Doua familii, pentru cele doua moduri de lucru ale agentului:

- ``Analysis*`` - analiza prin LLM (o parere argumentata, utila, dar o parere);
- ``Audit*`` - auditul determinist din ``seo_geo_agent/audit/``: crawl real,
  probleme verificabile, scoruri reproductibile. Asta e sursa de adevar a
  sectiunii SEO/GEO; analiza LLM se aseaza deasupra ei.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field

from seo_geo_agent.audit.issues import AUDIT_ISSUE_TYPES, ISSUE_SEVERITY_ORDER
from seo_geo_agent.audit.scoring import count_by_severity
from seo_geo_agent.audit.service import AuditResult
from seo_geo_agent.audit.store import AuditRecord


class AnalysisRequest(BaseModel):
    """Cererea de analiza SEO+GEO pentru un domeniu."""

    domain: str = Field(min_length=1, description="Domeniul analizat, ex. exemplu.ro")
    client_reports: str = Field(
        default="",
        description=(
            "Text brut OPTIONAL din rapoarte/unelte ale clientului (Ahrefs, Semrush, "
            "Google Search Console etc.). Se adauga la datele preluate automat de "
            "agent pentru domeniu (PageSpeed Insights + continutul paginii - vezi "
            "router.py), nu le inlocuieste - gol e valid, agentul tot analizeaza pe "
            "baza datelor auto-preluate."
        ),
    )
    target_audience: str | None = Field(
        default=None, description="Descrierea publicului tinta, daca e cunoscuta."
    )


class ActionableSuggestion(BaseModel):
    """O sugestie unica, actionabila - nu un sfat generic.

    ``exact_fix`` trebuie sa fie ceva ce un dezvoltator/marketer poate copia
    direct: cod JSON-LD, textul exact de schimbat, markup HTML precis - nu
    "imbunatateste continutul".
    """

    category: str = Field(description='Ex. "Schema Markup", "Entity Salience", "Continut".')
    current_issue: str = Field(description="Problema concreta gasita, pe baza datelor din cerere.")
    exact_fix: str = Field(
        description="Directiva tehnica exacta - cod, text, sau markup, nu vorbe goale."
    )


class AnalysisResponse(BaseModel):
    """Raspunsul complet al analizei: doua scoruri + doua liste de sugestii."""

    seo_score: int = Field(
        ge=0, le=100, description="Scor SEO clasic (motoare de cautare traditionale)."
    )
    geo_score: int = Field(
        ge=0,
        le=100,
        description="Scor GEO (Generative Engine Optimization - citabilitate in raspunsuri AI).",
    )
    seo_suggestions: list[ActionableSuggestion] = Field(default_factory=list)
    geo_suggestions: list[ActionableSuggestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audit determinist (seo_geo_agent/audit/)
# ---------------------------------------------------------------------------

#: Cate URL-uri afectate trimitem per tip de problema. Acelasi plafon ca in UI-ul
#: originalului (``MAX_RENDERED_URLS`` din ``IssuesView.tsx``): peste, lista
#: devine oricum necitibila, iar raspunsul se umfla degeaba.
MAX_AFFECTED_URLS_PER_ISSUE = 100

#: Plafonul de pagini pe care il accepta un audit. Peste atat, un singur proces
#: FastAPI fara coada de joburi nu mai e unealta potrivita.
MAX_AUDIT_PAGES = 100
MIN_AUDIT_PAGES = 1


class AuditRequest(BaseModel):
    """Cererea de audit pentru un domeniu."""

    domain: str = Field(
        min_length=1, max_length=2048, description="Domeniul auditat, ex. exemplu.ro"
    )
    #: Implicit tot plafonul: site-ul nu mai cere un numar de pagini, iar
    #: crawl-ul se opreste oricum singur cand nu mai gaseste pagini noi - un site
    #: mic nu costa mai mult, unul mare nu mai iese partial la o limita aleasa
    #: de mana. Routerul il mai taie o data la ``audit_max_pages`` din setari.
    max_pages: int = Field(
        default=MAX_AUDIT_PAGES,
        ge=MIN_AUDIT_PAGES,
        le=MAX_AUDIT_PAGES,
        description="Cate pagini are voie sa descarce crawl-ul. Implicit: plafonul serverului.",
    )
    brand: str = Field(
        default="",
        max_length=200,
        description=(
            "Numele exact al brandului, pentru verificarea GEO de entity salience. "
            "Gol => se deduce din domeniu (vezi audit/geo_reporters.py)."
        ),
    )


class AuditStartedResponse(BaseModel):
    """Confirmarea pornirii unui audit; raportul se ia separat, cand e gata."""

    audit_id: str
    status: Literal["running", "completed", "failed"]
    domain: str


class AuditStatusResponse(BaseModel):
    """Starea unui audit in derulare - ce afiseaza bara de progres."""

    audit_id: str
    status: Literal["running", "completed", "failed"]
    crawled: int
    queued: int
    max_pages: int
    error: str | None = None

    @classmethod
    def from_record(cls, record: AuditRecord) -> Self:
        return cls(
            audit_id=record.audit_id,
            status=record.status,
            crawled=record.progress.crawled,
            queued=record.progress.queued,
            max_pages=record.progress.max_pages,
            error=record.error,
        )


class AffectedPage(BaseModel):
    """O aparitie concreta a unei probleme: URL-ul si valorile masurate acolo."""

    page_url: str
    details: dict[str, Any] = Field(default_factory=dict)


class IssueGroup(BaseModel):
    """Toate aparitiile unui tip de problema, cu explicatia din registru.

    Gruparea pe tip (nu pe pagina) e decizia de prezentare a originalului:
    "40 de pagini fara meta description" e o singura sarcina de lucru, nu 40.
    """

    issue_type: str
    severity: Literal["critical", "warning", "info"]
    pillar: Literal["seo", "geo"]
    title: str
    explanation: str
    how_to_fix: str
    count: int
    affected_pages: list[AffectedPage]


class AuditPageRow(BaseModel):
    """O pagina crawlata, asa cum apare in tabelul de pagini."""

    url: str
    status_code: int
    fetch_class: Literal["ok", "blocked", "rate_limited", "error"]
    title: str
    meta_description: str
    word_count: int
    h1_count: int
    images_total: int
    images_missing_alt: int
    internal_links: int
    response_time_ms: int
    is_indexable: bool
    has_structured_data: bool
    crawl_depth: int | None
    in_sitemap: bool
    issue_count: int


class PillarScoreResponse(BaseModel):
    """Un scor, impreuna cu numerele din care a iesit - ca sa poata fi verificat."""

    score: int = Field(ge=0, le=100)
    checks_run: int
    checks_failed: int


class AuditSummary(BaseModel):
    """Rezumatul auditului: cat s-a masurat si cat de complet e raportul."""

    pages_crawled: int
    completed: bool = Field(
        description="False = crawl-ul s-a oprit din buget (pagini/timp), deci raportul e partial."
    )
    robots_txt_found: bool
    llms_txt_found: bool
    sitemap_urls_found: int
    critical_count: int
    warning_count: int
    info_count: int
    blocked_pages: int
    rate_limited_pages: int
    started_at: datetime
    finished_at: datetime


class AuditResultsResponse(BaseModel):
    """Raportul complet al unui audit terminat."""

    audit_id: str
    domain: str
    start_url: str
    brand: str
    summary: AuditSummary
    seo: PillarScoreResponse
    geo: PillarScoreResponse
    issues: list[IssueGroup]
    pages: list[AuditPageRow]

    @classmethod
    def from_result(cls, audit_id: str, domain: str, result: AuditResult) -> Self:
        """Transforma raportul intern in raspunsul API (gruparea problemelor se face aici)."""
        grouped: dict[str, list[AffectedPage]] = {}
        issues_per_page: dict[str, int] = {}
        for issue in result.issues:
            grouped.setdefault(issue.issue_type, []).append(
                AffectedPage(page_url=issue.page_url, details=issue.details)
            )
            issues_per_page[issue.page_url] = issues_per_page.get(issue.page_url, 0) + 1

        groups: list[IssueGroup] = []
        for issue_type, affected in grouped.items():
            descriptor = AUDIT_ISSUE_TYPES.get(issue_type)
            if descriptor is None:  # pragma: no cover - registrul acopera tot ce emitem
                continue
            groups.append(
                IssueGroup(
                    issue_type=issue_type,
                    severity=descriptor.severity,
                    pillar=descriptor.pillar,
                    title=descriptor.title,
                    explanation=descriptor.explanation,
                    how_to_fix=descriptor.how_to_fix,
                    count=len(affected),
                    affected_pages=affected[:MAX_AFFECTED_URLS_PER_ISSUE],
                )
            )
        # Intai dupa severitate, apoi dupa cate pagini sunt atinse - aceeasi
        # ordine ca in ``IssuesView.tsx`` din original.
        groups.sort(key=lambda group: (ISSUE_SEVERITY_ORDER[group.severity], -group.count))

        counts = count_by_severity(result.issues)
        return cls(
            audit_id=audit_id,
            domain=domain,
            start_url=result.start_url,
            brand=result.brand,
            summary=AuditSummary(
                pages_crawled=len(result.pages),
                completed=result.completed,
                robots_txt_found=result.robots_txt_found,
                llms_txt_found=result.llms_txt_found,
                sitemap_urls_found=result.sitemap_urls_found,
                critical_count=counts["critical"],
                warning_count=counts["warning"],
                info_count=counts["info"],
                blocked_pages=sum(1 for page in result.pages if page.fetch_class == "blocked"),
                rate_limited_pages=sum(
                    1 for page in result.pages if page.fetch_class == "rate_limited"
                ),
                started_at=result.started_at,
                finished_at=result.finished_at,
            ),
            seo=PillarScoreResponse(
                score=result.scores["seo"].score,
                checks_run=result.scores["seo"].checks_run,
                checks_failed=result.scores["seo"].checks_failed,
            ),
            geo=PillarScoreResponse(
                score=result.scores["geo"].score,
                checks_run=result.scores["geo"].checks_run,
                checks_failed=result.scores["geo"].checks_failed,
            ),
            issues=groups,
            pages=[
                AuditPageRow(
                    url=page.url,
                    status_code=page.status_code,
                    fetch_class=page.fetch_class,
                    title=page.title,
                    meta_description=page.meta_description,
                    word_count=page.word_count,
                    h1_count=page.h1_count,
                    images_total=page.images_total,
                    images_missing_alt=page.images_missing_alt,
                    internal_links=sum(1 for link in page.links if link.is_internal),
                    response_time_ms=page.response_time_ms,
                    is_indexable=page.is_indexable,
                    has_structured_data=page.structured_data.present,
                    crawl_depth=page.crawl_depth,
                    in_sitemap=page.in_sitemap,
                    issue_count=issues_per_page.get(page.url, 0),
                )
                for page in result.pages
            ],
        )
