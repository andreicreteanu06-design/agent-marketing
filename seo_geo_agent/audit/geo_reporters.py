"""Verificarile GEO: cat de citabil e site-ul de catre motoarele generative.

``every-app/open-seo`` masoara vizibilitatea AI din AFARA site-ului (mentiuni si
citari luate prin DataForSEO: ``src/server/features/ai-search/``). Aici masuram
cealalta jumatate - partea pe care o controleaza site-ul si care se poate
verifica direct din crawl - dar cu exact aceeasi disciplina ca verificarile SEO:
fiecare problema are un prag explicit, o dovada masurata si un id stabil.

===============================  =======  ======================================
prag                             valoare  de ce
===============================  =======  ======================================
JS_ONLY_MIN_HTML_BYTES            20_000  sub atat, HTML-ul mic poate fi legitim
JS_ONLY_MAX_WORDS                     50  HTML mare + text zero = randare in browser
ENTITY_SALIENCE_MIN_MENTIONS           3  sub 3 mentiuni, pasajul nu se atribuie
CONTENT_PAGE_MIN_WORDS               300  sub atat, pagina nu e una de continut
MAX_AVERAGE_SENTENCE_WORDS            30  peste, pasajul nu se extrage izolat
MIN_SENTENCES_FOR_LENGTH_CHECK         5  sub atat, media nu spune nimic
===============================  =======  ======================================

Verificarile care privesc tot site-ul (robots.txt, llms.txt, schema
Organization) se raporteaza O SINGURA data, pe URL-ul de start - nu o data per
pagina, ca sa nu umfle raportul cu acelasi lucru de 40 de ori.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from seo_geo_agent.audit.page_reporters import DetectedIssue
from seo_geo_agent.audit.robots import AI_CRAWLERS, RobotsTxt
from seo_geo_agent.audit.types import CrawledPage

JS_ONLY_MIN_HTML_BYTES = 20_000
JS_ONLY_MAX_WORDS = 50
ENTITY_SALIENCE_MIN_MENTIONS = 3
CONTENT_PAGE_MIN_WORDS = 300
MAX_AVERAGE_SENTENCE_WORDS = 30
MIN_SENTENCES_FOR_LENGTH_CHECK = 5

#: Tipurile JSON-LD care declara entitatea detinatoare a site-ului.
_ORGANIZATION_TYPES = frozenset(
    {"organization", "localbusiness", "corporation", "ngo", "person", "website"}
)

#: Inceputuri de intrebare in romana si engleza. Un titlu care incepe asa (sau
#: se termina cu "?") e un carlig pe care un motor generativ il poate folosi
#: direct ca intrebare de utilizator.
_QUESTION_STARTERS = (
    "ce ",
    "cum ",
    "cat ",
    "cât ",
    "care ",
    "cand ",
    "când ",
    "unde ",
    "cine ",
    "de ce",
    "what ",
    "how ",
    "why ",
    "when ",
    "where ",
    "which ",
    "who ",
    "is ",
    "can ",
    "should ",
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s|$)")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def brand_token_from_url(url: str) -> str:
    """Numele de brand dedus din domeniu: ``www.ac-media.ro`` -> ``ac media``.

    Aproximare deliberata si transparenta - nu incercam sa ghicim brandul din
    continut. Clientul poate trimite numele exact in cererea de audit; cand nu
    o face, eticheta asta e ce ar deduce si un cititor din URL.
    """
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    label = host.split(".")[0] if host else ""
    return label.replace("-", " ").strip()


def count_brand_mentions(text: str, brand: str) -> int:
    """De cate ori apare ``brand`` in ``text``, insensibil la litere mari/mici.

    Brandurile din mai multe cuvinte se cauta ca expresie; spatiile din brand
    accepta si cratima (``ac media`` prinde si ``ac-media``).
    """
    tokens = [re.escape(part) for part in brand.split() if part]
    if not tokens:
        return 0
    pattern = re.compile(r"\b" + r"[\s-]*".join(tokens) + r"\b", re.IGNORECASE)
    return len(pattern.findall(text))


def _average_sentence_words(text: str) -> tuple[float, int]:
    """``(media de cuvinte pe propozitie, numarul de propozitii)`` pentru ``text``."""
    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if not sentences:
        return 0.0, 0
    total_words = sum(len(_WORD_RE.findall(sentence)) for sentence in sentences)
    return total_words / len(sentences), len(sentences)


def _is_question_heading(text: str) -> bool:
    value = text.strip().lower()
    return value.endswith("?") or value.startswith(_QUESTION_STARTERS)


def run_geo_page_reporters(page: CrawledPage, brand: str) -> list[DetectedIssue]:
    """Problemele GEO vizibile din datele unei singure pagini."""
    issues: list[DetectedIssue] = []

    def report(issue_type: str, **details: object) -> None:
        issues.append(DetectedIssue(issue_type=issue_type, page_url=page.url, details=details))

    if not page.is_html or page.fetch_class != "ok" or page.status_code >= 300:
        return issues

    # HTML mare, text aproape inexistent: pagina se compune in browser, iar
    # crawler-ele AI nu ruleaza JavaScript. Asta le exclude complet, nu partial.
    if page.html_bytes >= JS_ONLY_MIN_HTML_BYTES and page.word_count < JS_ONLY_MAX_WORDS:
        report(
            "content-requires-javascript",
            html_bytes=page.html_bytes,
            word_count=page.word_count,
        )
        return issues  # restul verificarilor ar masura o pagina goala

    if not page.is_indexable:
        return issues  # o pagina pe noindex nu e menita sa fie citata

    if not page.structured_data.present:
        report("missing-structured-data")

    if brand and page.word_count >= CONTENT_PAGE_MIN_WORDS:
        mentions = count_brand_mentions(page.body_text, brand)
        if mentions < ENTITY_SALIENCE_MIN_MENTIONS:
            report("low-entity-salience", brand=brand, mentions=mentions)

    if page.word_count >= CONTENT_PAGE_MIN_WORDS:
        subheadings = [text for level, text in page.headings if level in (2, 3) and text]
        if subheadings and not any(_is_question_heading(text) for text in subheadings):
            report("no-answerable-headings", subheading_count=len(subheadings))

        average_words, sentence_count = _average_sentence_words(page.body_text)
        if (
            sentence_count >= MIN_SENTENCES_FOR_LENGTH_CHECK
            and average_words > MAX_AVERAGE_SENTENCE_WORDS
        ):
            report(
                "long-passages",
                average_sentence_words=round(average_words, 1),
                sentence_count=sentence_count,
            )

        has_author = bool(page.meta_author) or page.structured_data.has_author
        if not has_author and not page.structured_data.has_date:
            report("missing-author-signals")

    return issues


def run_geo_site_reporters(
    start_url: str,
    robots: RobotsTxt,
    *,
    homepage: CrawledPage | None,
    llms_txt_found: bool,
) -> list[DetectedIssue]:
    """Problemele GEO care privesc site-ul intreg, raportate o singura data."""
    issues: list[DetectedIssue] = []

    blocked = [
        f"{agent} ({label})"
        for agent, label in AI_CRAWLERS.items()
        if robots.blocks_any_path_for(agent)
    ]
    if blocked:
        issues.append(
            DetectedIssue(
                issue_type="ai-crawler-blocked",
                page_url=start_url,
                details={"blocked_crawlers": blocked},
            )
        )

    if not llms_txt_found:
        issues.append(DetectedIssue(issue_type="missing-llms-txt", page_url=start_url))

    if homepage is not None and homepage.is_html:
        declared = {value.lower() for value in homepage.structured_data.types}
        if not declared & _ORGANIZATION_TYPES:
            issues.append(
                DetectedIssue(
                    issue_type="missing-organization-schema",
                    page_url=homepage.url,
                    details={"declared_types": sorted(declared)},
                )
            )

    return issues
