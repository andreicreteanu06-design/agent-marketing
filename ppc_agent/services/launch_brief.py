"""Brief-ul de lansare: ce spun agentii SEO/GEO si PPC inainte ca o campanie sa intre in coada.

Pana aici, o lansare lua bugetul si textul exact cum veneau in cerere. Brief-ul
aduna patru lucruri inainte ca propunerea sa ajunga la omul care o aproba:

1. **Pagina de destinatie, prin ochii agentului SEO/GEO.** Aceeasi analiza si
   aceleasi verificari ca auditul (``seo_geo_agent.audit``), pe pagina catre
   care ar merge vizitatorii platiti.
2. **Fezabilitatea, prin matematica agentului PPC.** Iese sau nu campania din
   faza de invatare Meta (formula Modulului 3) si cate variante suporta bugetul
   (``decision/budget_strategy.py``).
3. **Pozitia in cont, prin Kelly si Thompson** - doar cand contul are istoric.
4. **Semnale pentru mesaj, din Modulul 1**: ce cauta oamenii (Search Console,
   Keyword Planner) si ce spun clientii (Business Profile).

Agentul PPC e cel care INTERPRETEAZA ce raporteaza agentul SEO/GEO. Auditul e
scris pentru motoarele de cautare; o pagina de reclama e judecata de un vizitator
care tocmai a dat click. Lungimea meta description-ului sau ``noindex`` nu-l
intereseaza pe el - o pagina lenta sau fara titlu, da. Brief-ul le arata pe toate,
dar ridica la avertisment doar ce costa bani.

**Blocheaza doar ce e obiectiv:** o pagina de destinatie care nu exista pentru un
vizitator (404/410) sau care nu e o adresa publica. Acolo banii s-ar pierde cu
certitudine. Tot restul e avertisment, iar omul decide.

O sursa indisponibila (cont Google neconectat, acces Business Profile inca
neaprobat) apare in brief ca atare - nu blocheaza si nu opreste brief-ul.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

from ppc_agent.alignment.meta_liquidity import (
    LEARNING_EVENTS,
    LEARNING_WINDOW_DAYS,
    learning_exit_days,
)
from ppc_agent.config import AppConfig, ProviderMode
from ppc_agent.decision.budget import ThompsonBudgetAllocator
from ppc_agent.decision.budget_strategy import recommend_arm_capacity
from ppc_agent.decision.kelly_sizing import size_daily_budget
from ppc_agent.decision.pipeline import arms_from_performance
from ppc_agent.errors import CrawlBlockedError, CrawlTargetBlockedError, CrawlTimeoutError
from ppc_agent.guardrails.spend_limiter import HARD_CEILING
from ppc_agent.ingestion.organic import to_local_signals
from ppc_agent.providers.base import (
    CrawlerProvider,
    GbpProvider,
    GscProvider,
    KeywordPlannerProvider,
    MetaMarketingProvider,
)
from ppc_agent.providers.meta_campaign import MetaLaunchSpec
from ppc_agent.texttools import tokenize
from seo_geo_agent.audit.crawler import page_from_html
from seo_geo_agent.audit.issues import AUDIT_ISSUE_TYPES
from seo_geo_agent.audit.page_reporters import DetectedIssue, run_page_reporters

logger = logging.getLogger("ppc_agent.services.launch_brief")

BRIEF_VERSION = 1
Verdict = Literal["ok", "warnings", "blocked"]

_CENT = Decimal("0.01")
_TOP_N = 5
#: Seed fix pentru Thompson: acelasi istoric trebuie sa dea acelasi brief.
_THOMPSON_SEED = 7
#: Locatia folosita de furnizorul ``mock`` (vezi ``ingestion/pipeline.py``).
_MOCK_GBP_LOCATION = "mock-location"

#: Codurile la care pagina obiectiv nu exista pentru un vizitator.
_GONE_STATUSES = frozenset({404, 410})

#: Verificarile agentului SEO/GEO care conteaza si pentru un vizitator platit,
#: cu motivul. Restul (lungimea titlului si a meta description-ului, canonical,
#: alt-ul imaginilor, noindex...) sunt scrise pentru motoarele de cautare: le
#: aratam, dar nu le ridicam la avertisment - altfel omul invata sa ignore brief-ul.
_PAID_TRAFFIC_ISSUES: dict[str, str] = {
    "server-error": "vizitatorii platiti ar vedea o eroare de server",
    "broken-page": "pagina raspunde cu o eroare, nu cu continut",
    "slow-response": "fiecare secunda de incarcare pierde o parte din click-urile platite",
    "missing-h1": "vizitatorul nu vede un titlu care sa continue promisiunea din reclama",
    "thin-content": "o pagina cu foarte putin text convinge greu un vizitator venit din reclama",
}
_SEO_ONLY_NOTES: dict[str, str] = {
    "noindex-page": (
        "normal pentru paginile de reclama - conteaza doar daca vrei pagina si in "
        "rezultatele organice Google"
    ),
}
_SEO_ONLY_DEFAULT = (
    "semnal pentru motoarele de cautare - nu afecteaza direct vizitatorii din reclama"
)

_NO_HISTORY_NOTE = (
    "Fara istoric in contul Meta: Kelly si Thompson n-au pe ce estima. Campania porneste "
    "ca buget de explorare; amandoua intra in calcul dupa primele conversii (Modulul 2)."
)
_MARKOV_NOTE = (
    "Markov nu intra in decizia de lansare: atribuie conversiile pe parcursurile reale ale "
    "clientilor, iar o campanie care nu exista inca n-are niciunul. Intra dupa lansare, "
    "in planul zilnic (run_plan)."
)


class BriefSources(Protocol):
    """De unde isi ia brief-ul datele. ``ProviderFactory`` il satisface ca atare."""

    def crawler(self) -> CrawlerProvider: ...
    def gsc(self) -> GscProvider: ...
    def keyword_planner(self) -> KeywordPlannerProvider: ...
    def gbp(self) -> GbpProvider: ...
    def meta(self) -> MetaMarketingProvider: ...


@dataclass(slots=True)
class LaunchBrief:
    """Ce stim despre o lansare inainte ca ea sa ajunga la aprobare.

    Trei niveluri, fiecare cu alt rol pentru omul care citeste:

    - ``blocking``: motive obiective pentru care lansarea NU intra in coada;
    - ``warnings``: riscuri care costa bani - omul decide daca le accepta;
    - ``suggestions``: ce ar putea imbunatati campania, fara sa fie o problema.
    """

    mode: str
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    landing_page: dict[str, Any] = field(default_factory=dict)
    learning_phase: dict[str, Any] = field(default_factory=dict)
    budget_position: dict[str, Any] = field(default_factory=dict)
    message_signals: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> Verdict:
        if self.blocking:
            return "blocked"
        return "warnings" if self.warnings else "ok"

    def summary(self) -> str:
        """O fraza pentru ``rationale``; detaliile stau in :meth:`to_payload`."""
        verdict = {
            "ok": "fara probleme",
            "warnings": "cu avertismente",
            "blocked": "blocata",
        }[self.verdict]
        return (
            f"Brief de lansare: {verdict} - {len(self.blocking)} blocaje, "
            f"{len(self.warnings)} avertismente, {len(self.suggestions)} sugestii."
        )

    def to_payload(self) -> dict[str, Any]:
        """Forma JSON salvata in propunere, langa specificatia lansarii."""
        return {
            "brief_version": BRIEF_VERSION,
            "mode": self.mode,
            "verdict": self.verdict,
            "blocking": list(self.blocking),
            "warnings": list(self.warnings),
            "suggestions": list(self.suggestions),
            "landing_page": self.landing_page,
            "learning_phase": self.learning_phase,
            "budget_position": self.budget_position,
            "markov": _MARKOV_NOTE,
            "message_signals": self.message_signals,
        }


def build_launch_brief(
    sources: BriefSources,
    config: AppConfig,
    spec: MetaLaunchSpec,
    *,
    ad_account: str,
    committed_daily_spend: Decimal = Decimal("0"),
) -> LaunchBrief:
    """Aduna parerea ambilor agenti despre o lansare.

    Args:
        sources: Furnizorii de date - in productie, ``ProviderFactory``.
        config: Configuratia clientului (CPA tinta, plafon, tara, limba).
        spec: Specificatia lansarii, deja validata.
        ad_account: Contul Meta in care s-ar crea campania (``act_...``).
        committed_daily_spend: Bugetul zilnic deja angajat de client - pentru
            comparatia cu plafonul Kelly.

    Returns:
        Brief-ul complet. Nu ridica exceptii pentru o sursa stricata: o sursa
        care pica apare ca indisponibila.
    """
    brief = LaunchBrief(mode=config.provider_mode.value)
    _landing_page(brief, sources, spec)
    _learning_phase(brief, config, spec)
    _budget_position(brief, sources, config, spec, ad_account, committed_daily_spend)
    _message_signals(brief, sources, config, spec)
    return brief


def _unavailable(exc: Exception) -> dict[str, Any]:
    logger.info("sursa brief-ului indisponibila: %s: %s", type(exc).__name__, exc)
    return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


# --- 1. pagina de destinatie (agentul SEO/GEO) -----------------------------


def _describe(issue: DetectedIssue) -> dict[str, Any]:
    """O problema a auditului, cu textul registrului si motivul pentru reclama."""
    descriptor = AUDIT_ISSUE_TYPES.get(issue.issue_type)
    why = _PAID_TRAFFIC_ISSUES.get(issue.issue_type) or _SEO_ONLY_NOTES.get(
        issue.issue_type, _SEO_ONLY_DEFAULT
    )
    return {
        "id": issue.issue_type,
        "severity": descriptor.severity if descriptor else "info",
        "title": descriptor.title if descriptor else issue.issue_type,
        "how_to_fix": descriptor.how_to_fix if descriptor else "",
        "details": dict(issue.details),
        "for_paid_traffic": why,
    }


PixelPresence = Literal["found", "other_pixel", "tag_manager", "missing"]


def pixel_presence(html: str, pixel_id: str) -> PixelPresence:
    """Ce se vede in HTML despre pixelul Meta al campaniei.

    Doar HTML-ul brut, fara sa executam JavaScript: un pixel incarcat prin Google
    Tag Manager sau de un plugin nu apare aici. De-asta ``tag_manager`` si
    ``missing`` sunt semnale de verificat, nu dovezi.
    """
    lowered = html.lower()
    meta_pixel = any(
        marker in lowered for marker in ("connect.facebook.net", "fbq(", "facebook.com/tr")
    )
    if meta_pixel:
        return "found" if pixel_id in html else "other_pixel"
    if "googletagmanager.com/" in lowered:
        return "tag_manager"
    return "missing"


def _landing_page(brief: LaunchBrief, sources: BriefSources, spec: MetaLaunchSpec) -> None:
    section: dict[str, Any] = {"url": spec.target_url}
    brief.landing_page = section

    started = time.monotonic()
    try:
        fetched = sources.crawler().fetch(spec.target_url)
    except CrawlTargetBlockedError as exc:
        section["status"] = "not_public"
        brief.blocking.append(
            f"pagina de destinatie '{spec.target_url}' nu e o adresa publica ({exc}) - "
            "niciun vizitator n-ar ajunge pe ea"
        )
        return
    except CrawlBlockedError as exc:
        section["status"] = "unverified"
        brief.warnings.append(
            f"site-ul a oprit crawler-ul nostru ({exc}); pagina n-a putut fi verificata - "
            "deschide-o manual inainte de aprobare"
        )
        return
    except CrawlTimeoutError as exc:
        section["status"] = "unverified"
        brief.warnings.append(
            f"pagina de destinatie n-a raspuns la timp ({exc}); daca e la fel de lenta si "
            "pentru vizitatori, pierzi click-uri platite"
        )
        return
    except Exception as exc:
        # Retea, DNS, raspuns ciudat: NU blocam - nu putem distinge sigur intre o
        # pagina moarta si o problema de retea de partea noastra.
        section["status"] = "unverified"
        brief.warnings.append(
            f"pagina de destinatie n-a putut fi accesata ({type(exc).__name__}: {exc}); "
            "verifica ca domeniul raspunde"
        )
        return
    elapsed_ms = int((time.monotonic() - started) * 1000)
    final_url = fetched.final_url or spec.target_url
    section.update(
        final_url=final_url,
        status_code=fetched.status_code,
        response_time_ms=elapsed_ms,
    )

    if fetched.status_code in _GONE_STATUSES:
        section["status"] = "gone"
        brief.blocking.append(
            f"pagina de destinatie raspunde {fetched.status_code}: vizitatorii platiti ar "
            "ajunge pe o pagina care nu exista"
        )
        return
    if fetched.status_code < 400 and not fetched.html.strip():
        section["status"] = "not_html"
        brief.warnings.append(
            "pagina de destinatie nu intoarce HTML (sau e goala) - Meta poate refuza "
            "link-ul, iar vizitatorul nu vede o pagina"
        )
        return

    page = page_from_html(final_url, fetched.status_code, fetched.html, response_time_ms=elapsed_ms)
    described = [_describe(issue) for issue in run_page_reporters(page)]
    paid = [item for item in described if item["id"] in _PAID_TRAFFIC_ISSUES]
    seo_only = [item for item in described if item["id"] not in _PAID_TRAFFIC_ISSUES]
    for item in paid:
        brief.warnings.append(f"pagina de destinatie: {item['title']} - {item['for_paid_traffic']}")

    pixel = pixel_presence(fetched.html, spec.pixel_id)
    if pixel == "missing":
        brief.warnings.append(
            f"pixelul {spec.pixel_id} nu apare in HTML-ul paginii: fara el, optimizarea pe "
            f"{spec.custom_event_type} nu primeste evenimente. Daca e incarcat altfel "
            "(plugin, server-side), ignora avertismentul."
        )
    elif pixel == "other_pixel":
        brief.warnings.append(
            f"pagina incarca un pixel Meta, dar nu pe {spec.pixel_id} din campanie - "
            "conversiile ar ajunge in alt pixel decat cel pe care optimizeaza campania"
        )
    elif pixel == "tag_manager":
        brief.suggestions.append(
            f"pagina incarca Google Tag Manager; pixelul {spec.pixel_id} poate fi acolo - "
            "confirma in Meta Events Manager ca primeste evenimente"
        )

    section.update(
        status="ok",
        title=page.title,
        h1=[text for level, text in page.headings if level == 1],
        word_count=page.word_count,
        indexable=page.is_indexable,
        pixel=pixel,
        paid_traffic_issues=paid,
        seo_only_issues=seo_only,
    )


# --- 2. faza de invatare si capacitatea bugetului (agentul PPC) ------------


def _learning_phase(brief: LaunchBrief, config: AppConfig, spec: MetaLaunchSpec) -> None:
    target_cpa = config.budget.target_cpa
    if target_cpa is None or target_cpa <= 0:
        brief.learning_phase = {
            "status": "unavailable",
            "reason": "CPA-ul tinta al clientului nu e setat (default_lead_value)",
        }
        return

    window = Decimal(str(LEARNING_WINDOW_DAYS))
    threshold = Decimal(str(LEARNING_EVENTS))
    weekly = spec.daily_budget / target_cpa * window
    exit_days = learning_exit_days(float(weekly), LEARNING_EVENTS)
    max_cpa = (spec.daily_budget * window / threshold).quantize(_CENT)
    budget_needed = (target_cpa * threshold / window).quantize(_CENT)
    capacity = recommend_arm_capacity(spec.daily_budget, target_cpa)

    brief.learning_phase = {
        "status": "ok",
        "event": spec.custom_event_type,
        "daily_budget": str(spec.daily_budget),
        "target_cpa": str(target_cpa),
        "target_cpa_source": "ClientAccount.default_lead_value",
        "expected_events_per_week": str(weekly.quantize(Decimal("0.1"))),
        "required_events_per_week": int(LEARNING_EVENTS),
        "window_days": int(LEARNING_WINDOW_DAYS),
        "exits_learning": exit_days is not None,
        "days_to_exit": exit_days,
        "max_cpa_to_exit": str(max_cpa),
        "budget_needed_at_target_cpa": str(budget_needed),
        "capacity": {
            "tier": capacity.tier,
            "max_concurrent_arms": capacity.recommended_max_concurrent_arms,
            "min_arm_daily_spend": str(capacity.recommended_min_arm_daily_spend),
            "rationale": capacity.rationale,
        },
    }
    if exit_days is None:
        brief.warnings.append(
            f"faza de invatare: la {spec.daily_budget}/zi si un CPA tinta de {target_cpa}, "
            f"ies ~{weekly:.1f} evenimente {spec.custom_event_type} pe saptamana, iar Meta "
            f"cere ~{LEARNING_EVENTS:.0f}. Campania va ramane in Learning Limited. Ca sa "
            f"iasa: CPA sub {max_cpa}, sau ~{budget_needed}/zi la CPA-ul tinta, sau "
            f"optimizare pe un eveniment mai frecvent decat {spec.custom_event_type}. "
            "Altfel, trateaz-o explicit ca test."
        )


# --- 3. pozitia in cont: Kelly si Thompson (agentul PPC) --------------------


def _budget_position(
    brief: LaunchBrief,
    sources: BriefSources,
    config: AppConfig,
    spec: MetaLaunchSpec,
    ad_account: str,
    committed: Decimal,
) -> None:
    section: dict[str, Any] = {}
    brief.budget_position = section
    try:
        frame = sources.meta().campaign_performance(ad_account)
    except Exception as exc:
        section.update(_unavailable(exc))
        return

    arms = [
        arm
        for arm in arms_from_performance(
            frame, platform="meta_ads", lead_value=config.budget.lead_value
        )
        if arm.clicks > 0
    ]
    if not arms:
        section.update(status="no_history", note=_NO_HISTORY_NOTE)
        return

    try:
        kelly = size_daily_budget(
            arms, baseline_cap=config.budget.max_daily_spend, hard_ceiling=HARD_CEILING
        )
    except Exception as exc:
        section.update(_unavailable(exc))
        return

    total_after = committed + spec.daily_budget
    section.update(
        status="ok",
        arms_considered=len(arms),
        committed_daily_spend=str(committed),
        total_after_launch=str(total_after),
        kelly={
            "sized_daily_cap": str(kelly.sized_daily_cap),
            "edge": kelly.edge,
            "win_prob": round(kelly.win_prob, 4),
            "rationale": kelly.rationale,
        },
    )
    if total_after > kelly.sized_daily_cap:
        brief.warnings.append(
            f"Kelly: istoricul contului justifica ~{kelly.sized_daily_cap}/zi in total; cu "
            f"lansarea asta, bugetul zilnic angajat ajunge la {total_after}"
        )
    if kelly.sized_daily_cap <= 0:
        return

    # Campania noua NU intra ca brat in Thompson: fara date, ar avea doar priorul
    # (media contului) si incertitudinea maxima - "castigul" ei ar fi un artefact
    # statistic, nu un semnal. Thompson ruleaza pe ce exista si spune ce trebuie
    # sa bata campania noua.
    try:
        plan = ThompsonBudgetAllocator().allocate(
            arms, float(kelly.sized_daily_cap), seed=_THOMPSON_SEED
        )
    except Exception as exc:
        section["thompson"] = _unavailable(exc)
        return
    best = max(plan.allocations, key=lambda allocation: allocation.win_probability)
    best_arm = next(arm for arm in arms if arm.arm_id == best.arm_id)
    best_cpa = (
        (best_arm.cost / best_arm.conversions).quantize(_CENT) if best_arm.conversions else None
    )
    section["thompson"] = {
        "status": "ok",
        "best_arm": best.name,
        "p_best": best.win_probability,
        "best_cpa": str(best_cpa) if best_cpa is not None else None,
    }
    if best_cpa is not None:
        brief.suggestions.append(
            f"Thompson: in contul Meta, '{best.name}' are cea mai mare sansa sa fie cel mai "
            f"bun set de reclame (P={best.win_probability:.2f}), la un CPA de {best_cpa}. "
            "Asta e tinta pe care trebuie s-o bata campania noua ca sa merite bugetul."
        )


# --- 4. semnale pentru mesaj (Modulul 1) -----------------------------------


def _uncovered_queries(queries: list[str], copy_text: str) -> list[str]:
    """Interogarile ale caror cuvinte nu apar deloc in textul reclamei."""
    copy_tokens = set(tokenize(copy_text))
    uncovered: list[str] = []
    for query in queries:
        tokens = [token for token in tokenize(query) if len(token) > 2]
        if tokens and not any(token in copy_tokens for token in tokens):
            uncovered.append(query)
    return uncovered


def _message_signals(
    brief: LaunchBrief, sources: BriefSources, config: AppConfig, spec: MetaLaunchSpec
) -> None:
    section: dict[str, Any] = {}
    brief.message_signals = section

    queries: list[str] = []
    try:
        frame = sources.gsc().top_queries(config.target_domain)
        top = frame.sort_values("clicks", ascending=False).head(_TOP_N)
        rows: list[dict[str, Any]] = [
            {
                "query": str(record["query"]),
                "clicks": int(record["clicks"]),
                "impressions": int(record["impressions"]),
                "position": float(record["position"]),
            }
            for record in top.to_dict(orient="records")
        ]
        queries = [row["query"] for row in rows]
        section["gsc"] = {"status": "ok", "top_queries": rows}
    except Exception as exc:
        section["gsc"] = _unavailable(exc)

    try:
        seeds = queries or [config.target_domain]
        frame = sources.keyword_planner().expand(seeds, config.geo, config.language)
        top = frame.sort_values("avg_monthly_searches", ascending=False).head(_TOP_N)
        section["keyword_planner"] = {
            "status": "ok",
            "ideas": [
                {
                    "keyword": str(record["keyword"]),
                    "avg_monthly_searches": int(record["avg_monthly_searches"]),
                    "low_top_bid": float(record["low_top_bid"]),
                    "high_top_bid": float(record["high_top_bid"]),
                }
                for record in top.to_dict(orient="records")
            ],
        }
    except Exception as exc:
        section["keyword_planner"] = _unavailable(exc)

    uncovered = _uncovered_queries(queries[:3], f"{spec.headline} {spec.primary_text}")
    if queries and len(uncovered) == len(queries[:3]):
        brief.suggestions.append(
            "textul reclamei nu foloseste niciunul dintre termenii pe care site-ul deja "
            f"aduce trafic organic: {', '.join(uncovered)}. Un unghi deja validat de "
            "cautari reale e un test ieftin."
        )

    location = config.settings.gbp_location_id
    if not location and config.provider_mode is ProviderMode.LIVE:
        section["gbp"] = {
            "status": "unavailable",
            "reason": "nicio locatie Business Profile configurata (PPC_GBP_LOCATION_ID)",
        }
        return
    try:
        signals = to_local_signals(sources.gbp().local_signals(location or _MOCK_GBP_LOCATION))
    except Exception as exc:
        section["gbp"] = _unavailable(exc)
        return

    negative = sum(1 for review in signals.reviews if review.label == "negativ")
    negative_share = round(negative / len(signals.reviews), 2) if signals.reviews else None
    section["gbp"] = {
        "status": "ok",
        "name": signals.name,
        "avg_rating": signals.avg_rating,
        "review_count": signals.review_count,
        "negative_share": negative_share,
    }
    if signals.review_count >= 5 and signals.avg_rating < 4.0:
        brief.warnings.append(
            f"ratingul Google Business Profile e {signals.avg_rating:.1f} din "
            f"{signals.review_count} recenzii - vizitatorii din reclama verifica recenziile, "
            "asteapta-te la o conversie mai slaba"
        )
    elif signals.review_count >= 20 and signals.avg_rating >= 4.5:
        brief.suggestions.append(
            f"{signals.avg_rating:.1f} stele din {signals.review_count} recenzii Google - "
            "dovada sociala care merita pusa in textul reclamei"
        )
