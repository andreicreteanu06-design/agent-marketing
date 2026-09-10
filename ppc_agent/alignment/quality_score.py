"""Optimizator de Quality Score: aliniaza copy-ul de anunt cu keyword-ul si landing-ul.

Nu genereaza copy si nu apeleaza niciun LLM. Primeste headline-uri / descrieri ca
text si le compara cu cuvantul cheie exact-match si cu ``PageContext`` (H1/H2).
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ppc_agent.alignment.models import AdGroupInput, QsRating, QualityScoreReport
from ppc_agent.ingestion.models import PageContext
from ppc_agent.texttools import contains_phrase, normalize, tokenize

_WEIGHTS: dict[str, float] = {
    "keyword_headline_coverage": 0.30,
    "keyword_landing_coverage": 0.30,
    "headline_h1_similarity": 0.25,
    "description_cta_alignment": 0.15,
}


def _coverage(keyword: str, texts: list[str]) -> float:
    """Fractia jetoanelor din keyword acoperite de reuniunea jetoanelor din ``texts``."""
    keyword_tokens = set(tokenize(keyword))
    if not keyword_tokens:
        return 0.0
    corpus_tokens: set[str] = set()
    for text in texts:
        corpus_tokens.update(tokenize(text))
    covered = keyword_tokens & corpus_tokens
    return len(covered) / len(keyword_tokens)


def _tfidf_cosine(left: str, right: str) -> float:
    """Similaritate cosine TF-IDF intre doua texte (0 daca vocabularul e gol)."""
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    try:
        matrix = TfidfVectorizer().fit_transform([left_norm, right_norm])
    except ValueError:
        return 0.0
    similarity = cosine_similarity(matrix[0:1], matrix[1:2])
    return round(float(similarity[0][0]), 6)


def _rating(value: float, *, high: float, avg: float) -> QsRating:
    if value >= high:
        return "High"
    if value >= avg:
        return "Avg"
    return "Low"


def analyze_ad_group(ad_group: AdGroupInput, page: PageContext) -> QualityScoreReport:
    """Estimeaza Quality Score pentru un grup de anunturi.

    Componente (fiecare in ``[0, 1]``):

    - ``keyword_headline_coverage`` — jetoane din keyword prezente in headline-uri
    - ``keyword_landing_coverage``  — jetoane din keyword prezente in H1/H2
    - ``headline_h1_similarity``    — cosine TF-IDF intre headline-uri si H1
    - ``description_cta_alignment`` — suprapunere jetoane descrieri <-> CTA-uri pagina

    Scorul 0-10 este media ponderata a componentelor inmultita cu 10.

    Regula stricta: daca keyword-ul exact-match lipseste si din H1, si din toate
    headline-urile, grupul este ``flagged`` iar Landing Page Experience devine Low.

    Args:
        ad_group: Copy-ul propus si keyword-ul exact-match.
        page: Contextul paginii de destinatie.

    Returns:
        Raportul de Quality Score cu note Low/Avg/High si sugestii concrete.
    """
    keyword = ad_group.exact_match_keyword
    headline_blob = " ".join(ad_group.headlines)
    h1_blob = " ".join(page.h1)
    h1_h2 = [*page.h1, *page.h2]

    kw_headline = _coverage(keyword, ad_group.headlines)
    kw_landing = _coverage(keyword, h1_h2)
    headline_h1_sim = _tfidf_cosine(headline_blob, h1_blob)
    desc_cta = (
        _coverage(" ".join(page.cta_texts), ad_group.descriptions)
        if page.cta_texts
        else 0.0
    )

    components = {
        "keyword_headline_coverage": round(kw_headline, 6),
        "keyword_landing_coverage": round(kw_landing, 6),
        "headline_h1_similarity": headline_h1_sim,
        "description_cta_alignment": round(desc_cta, 6),
    }
    score = round(
        10.0 * sum(_WEIGHTS[name] * value for name, value in components.items()), 2
    )

    keyword_in_h1 = any(contains_phrase(text, keyword) for text in page.h1)
    keyword_in_headlines = any(
        contains_phrase(text, keyword) for text in ad_group.headlines
    )
    flagged = not keyword_in_h1 and not keyword_in_headlines

    expected_ctr: QsRating = _rating(kw_headline, high=0.8, avg=0.4)
    if not keyword_in_headlines and expected_ctr == "High":
        expected_ctr = "Avg"
    ad_relevance = _rating((kw_headline + headline_h1_sim) / 2.0, high=0.55, avg=0.3)
    landing_page_experience: QsRating = (
        "Low" if not keyword_in_h1 else _rating(kw_landing, high=0.75, avg=0.4)
    )

    return QualityScoreReport(
        ad_group_id=ad_group.ad_group_id,
        name=ad_group.name,
        keyword=keyword,
        score=score,
        expected_ctr=expected_ctr,
        ad_relevance=ad_relevance,
        landing_page_experience=landing_page_experience,
        keyword_in_h1=keyword_in_h1,
        keyword_in_headlines=keyword_in_headlines,
        flagged=flagged,
        components=components,
        suggestions=_suggestions(
            keyword=keyword,
            keyword_in_h1=keyword_in_h1,
            keyword_in_headlines=keyword_in_headlines,
            headline_h1_sim=headline_h1_sim,
            kw_landing=kw_landing,
            desc_cta=desc_cta,
            has_ctas=bool(page.cta_texts),
        ),
    )


def analyze_ad_groups(
    ad_groups: list[AdGroupInput], page: PageContext
) -> list[QualityScoreReport]:
    """Ruleaza :func:`analyze_ad_group` pe fiecare grup, sortat descrescator dupa scor."""
    reports = [analyze_ad_group(ad_group, page) for ad_group in ad_groups]
    reports.sort(key=lambda report: report.score, reverse=True)
    return reports


def _suggestions(
    *,
    keyword: str,
    keyword_in_h1: bool,
    keyword_in_headlines: bool,
    headline_h1_sim: float,
    kw_landing: float,
    desc_cta: float,
    has_ctas: bool,
) -> list[str]:
    out: list[str] = []
    if not keyword_in_h1:
        out.append(
            f"H1 nu contine cuvantul cheie exact '{keyword}' - adauga-l in titlul paginii"
        )
    if not keyword_in_headlines:
        out.append(
            f"niciun titlu de anunt nu contine '{keyword}' - foloseste-l intr-un headline"
        )
    if headline_h1_sim < 0.3:
        out.append(
            "titlurile de anunt si H1 vorbesc despre lucruri diferite - aliniaza mesajul"
        )
    if kw_landing < 0.5:
        out.append("H1/H2 acopera slab cuvantul cheie - ajusteaza continutul paginii")
    if has_ctas and desc_cta < 0.3:
        out.append("descrierile nu reiau CTA-ul paginii de destinatie")
    return out
