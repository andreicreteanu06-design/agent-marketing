"""Scorurile SEO si GEO, derivate din problemele masurate.

``every-app/open-seo`` nu afiseaza un "health score" - afiseaza numaratori de
probleme pe severitate. Produsul asta vinde doua scoruri, deci avem nevoie de o
formula. Regula pe care o respecta: scorul sa fie DERIVAT din probleme, nu o
parere - reproductibil, explicabil si publicat.

Modelul e o rata de trecere ponderata, nu o penalizare inventata:

1. Fiecare pagina crawlata deschide un set de "sloturi de verificare"
   (:data:`CHECKS`). Un slot se deschide doar daca verificarea are sens pentru
   pagina aceea - un PDF nu deschide slotul de H1, o pagina de sub 300 de
   cuvinte nu deschide sloturile GEO de continut.
2. Un slot pica daca auditul a gasit o problema care il mapeaza
   (:data:`ISSUE_TO_CHECK`). Mai multe probleme in acelasi slot pe aceeasi
   pagina = o singura picare, nu trei.
3. ``scor = 100 * (1 - greutatea sloturilor picate / greutatea sloturilor deschise)``.

Consecinte pe care le voiam:

- un site intreg cazut (5xx peste tot) deschide doar slotul de disponibilitate
  si il pica peste tot => 0, nu "75 pentru ca e o singura problema";
- un site perfect, dar mic, nu iese avantajat fata de unul mare: totul e raportat
  la sloturile chiar deschise, nu la numarul de pagini;
- doua probleme pe care originalul le numeste intentionate (``noindex-page``,
  ``canonicalized-page``) NU intra in scor - ar pedepsi o configurare corecta.
  Raman in raport, ca informare.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from seo_geo_agent.audit.geo_reporters import CONTENT_PAGE_MIN_WORDS
from seo_geo_agent.audit.issues import AUDIT_ISSUE_TYPES, IssuePillar
from seo_geo_agent.audit.page_reporters import DetectedIssue
from seo_geo_agent.audit.types import CrawledPage

#: Greutatea unui slot, dupa cat de mult conteaza cand pica.
CRITICAL_WEIGHT: Final = 3.0
WARNING_WEIGHT: Final = 2.0
INFO_WEIGHT: Final = 1.0

CheckScope = Literal["page", "site"]


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    """Un slot de verificare: cand se deschide si cat cantareste daca pica."""

    check_id: str
    pillar: IssuePillar
    weight: float
    scope: CheckScope
    #: Pentru sloturile de pagina: se deschide pentru pagina asta? ``None``
    #: inseamna "pentru orice pagina crawlata".
    applies_to: Callable[[CrawledPage], bool] | None = None


def _is_fetched_html(page: CrawledPage) -> bool:
    return page.fetch_class == "ok" and 200 <= page.status_code < 300 and page.is_html


def _is_redirect(page: CrawledPage) -> bool:
    return 300 <= page.status_code < 400


def _is_content_page(page: CrawledPage) -> bool:
    """Pragul e IMPORTAT din ``geo_reporters``, nu copiat.

    Daca sloturile s-ar deschide dupa alt prag decat cel dupa care se emit
    problemele, ar exista verificari GEO care nu pot pica niciodata - sau
    probleme care pica un slot inexistent. Scorul ar deveni o minciuna mica.
    """
    return _is_fetched_html(page) and page.word_count >= CONTENT_PAGE_MIN_WORDS


CHECKS: Final[tuple[CheckDefinition, ...]] = (
    # --- SEO, per pagina ---------------------------------------------------
    CheckDefinition("availability", "seo", CRITICAL_WEIGHT, "page"),
    CheckDefinition("title-present", "seo", CRITICAL_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("title-length", "seo", INFO_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("meta-description-present", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("meta-description-length", "seo", INFO_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("h1", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("heading-order", "seo", INFO_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("canonical", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("content-depth", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("images-alt", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("outgoing-links", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("response-time", "seo", INFO_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("crawl-depth", "seo", INFO_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("unique-title", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("unique-meta-description", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("unique-content", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("internal-links-alive", "seo", CRITICAL_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("internally-linked", "seo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("redirect-health", "seo", WARNING_WEIGHT, "page", _is_redirect),
    # --- GEO, per pagina ---------------------------------------------------
    CheckDefinition("server-rendered-content", "geo", CRITICAL_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("structured-data", "geo", WARNING_WEIGHT, "page", _is_fetched_html),
    CheckDefinition("entity-salience", "geo", WARNING_WEIGHT, "page", _is_content_page),
    CheckDefinition("answerable-headings", "geo", INFO_WEIGHT, "page", _is_content_page),
    CheckDefinition("passage-length", "geo", INFO_WEIGHT, "page", _is_content_page),
    CheckDefinition("author-signals", "geo", INFO_WEIGHT, "page", _is_content_page),
    # --- GEO, la nivel de site (o singura data) ----------------------------
    CheckDefinition("ai-crawler-access", "geo", CRITICAL_WEIGHT, "site"),
    CheckDefinition("organization-schema", "geo", WARNING_WEIGHT, "site"),
    CheckDefinition("llms-txt", "geo", INFO_WEIGHT, "site"),
)

#: Ce slot pica fiecare tip de problema. ``None`` = problema ramane in raport,
#: dar nu intra in scor (vezi docstring-ul modulului).
ISSUE_TO_CHECK: Final[dict[str, str | None]] = {
    "blocked-page": "availability",
    "rate-limited-page": "availability",
    "crawl-rate-limited": None,  # avertisment despre raport, nu despre site
    "server-error": "availability",
    "broken-page": "availability",
    "missing-title": "title-present",
    "title-too-long": "title-length",
    "title-too-short": "title-length",
    "missing-meta-description": "meta-description-present",
    "meta-description-too-long": "meta-description-length",
    "meta-description-too-short": "meta-description-length",
    "missing-h1": "h1",
    "multiple-h1": "h1",
    "heading-order-skip": "heading-order",
    "canonical-conflict": "canonical",
    "canonicalized-page": None,  # de multe ori intentionat
    "noindex-page": None,  # de multe ori intentionat
    "thin-content": "content-depth",
    "images-missing-alt": "images-alt",
    "no-outgoing-links": "outgoing-links",
    "slow-response": "response-time",
    "deep-page": "crawl-depth",
    "duplicate-title": "unique-title",
    "duplicate-meta-description": "unique-meta-description",
    "duplicate-content": "unique-content",
    "broken-internal-link": "internal-links-alive",
    "orphan-page": "internally-linked",
    "redirect-chain": "redirect-health",
    "redirect-loop": "redirect-health",
    "content-requires-javascript": "server-rendered-content",
    "missing-structured-data": "structured-data",
    "low-entity-salience": "entity-salience",
    "no-answerable-headings": "answerable-headings",
    "long-passages": "passage-length",
    "missing-author-signals": "author-signals",
    "ai-crawler-blocked": "ai-crawler-access",
    "missing-organization-schema": "organization-schema",
    "missing-llms-txt": "llms-txt",
}

_CHECKS_BY_ID: Final[dict[str, CheckDefinition]] = {check.check_id: check for check in CHECKS}


@dataclass(frozen=True, slots=True)
class PillarScore:
    """Scorul unui pilon, impreuna cu numerele din care a iesit."""

    score: int
    checks_run: int
    checks_failed: int
    weight_total: float
    weight_failed: float


def _score_from_weights(weight_total: float, weight_failed: float) -> int:
    if weight_total <= 0:
        return 0
    ratio = max(0.0, min(1.0, weight_failed / weight_total))
    return round(100 * (1 - ratio))


def compute_pillar_scores(
    pages: list[CrawledPage], issues: list[DetectedIssue]
) -> dict[IssuePillar, PillarScore]:
    """Scorurile SEO si GEO pentru un audit, dupa modelul din docstring-ul modulului."""
    # Sloturile deschise: (check_id, url) pentru cele de pagina, (check_id, "")
    # pentru cele de site.
    open_slots: set[tuple[str, str]] = set()
    for check in CHECKS:
        if check.scope == "site":
            open_slots.add((check.check_id, ""))
            continue
        for page in pages:
            if check.applies_to is None or check.applies_to(page):
                open_slots.add((check.check_id, page.url))

    failed_slots: set[tuple[str, str]] = set()
    for issue in issues:
        check_id = ISSUE_TO_CHECK.get(issue.issue_type)
        if check_id is None:
            continue
        check = _CHECKS_BY_ID[check_id]
        slot = (check_id, "" if check.scope == "site" else issue.page_url)
        # O problema care pica un slot niciodata deschis (ex. un link rupt
        # raportat pe o pagina care intre timp a iesit din set) e ignorata:
        # scorul trebuie sa ramana o rata intre 0 si 1.
        if slot in open_slots:
            failed_slots.add(slot)

    scores: dict[IssuePillar, PillarScore] = {}
    pillars: tuple[IssuePillar, ...] = ("seo", "geo")
    for pillar in pillars:
        pillar_slots = [
            slot for slot in open_slots if _CHECKS_BY_ID[slot[0]].pillar == pillar
        ]
        pillar_failed = [
            slot for slot in failed_slots if _CHECKS_BY_ID[slot[0]].pillar == pillar
        ]
        weight_total = sum(_CHECKS_BY_ID[slot[0]].weight for slot in pillar_slots)
        weight_failed = sum(_CHECKS_BY_ID[slot[0]].weight for slot in pillar_failed)
        scores[pillar] = PillarScore(
            score=_score_from_weights(weight_total, weight_failed),
            checks_run=len(pillar_slots),
            checks_failed=len(pillar_failed),
            weight_total=round(weight_total, 2),
            weight_failed=round(weight_failed, 2),
        )
    return scores


def count_by_severity(issues: list[DetectedIssue]) -> dict[str, int]:
    """Cate probleme sunt de fiecare severitate (pentru rezumatul din UI)."""
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in issues:
        descriptor = AUDIT_ISSUE_TYPES.get(issue.issue_type)
        if descriptor is not None:
            counts[descriptor.severity] += 1
    return counts
