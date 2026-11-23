"""Testul de prezenta GEO: apare brandul cand clientii intreaba?

Scorul GEO din audit masoara cat de PREGATITA e o pagina sa fie citata
(server-side rendering, JSON-LD, titluri-intrebare, llms.txt). Nu masoara daca
brandul chiar apare in sursele din care motoarele generative isi compun
raspunsurile. Cazul real care a dus la modulul asta: un restaurant cu GEO 93/100
in audit, dar absent din raspunsuri la "cea mai buna pinsa romana din Bucuresti"
- desi revendica un premiu exact pentru asta. Motoarele citau liste "best of",
Tripadvisor, Wanderlog, presa locala.

Testul pune intrebarile pe care le-ar pune un client unui motor de cautare
(proxy pentru sursele pe care le citeaza ChatGPT, Perplexity, AI Overviews -
toate pornesc de la cautare) si raporteaza, pe intrebare:

- daca brandul apare in titlurile/fragmentele rezultatelor;
- daca domeniul brandului e printre rezultate (si pe ce pozitie);
- ce domenii apar in locul lui - sursele de cucerit (PR, listari, recenzii).

E un proxy, si raportul o spune: un motor generativ poate cita alte surse decat
primele rezultate de cautare. Logica de evaluare (:func:`evaluate_presence`) e
pura si testabila fara retea; cautarea e un :class:`SearchProvider` injectabil.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import urlsplit

from seo_geo_agent.audit.geo_reporters import count_brand_mentions
from seo_geo_agent.errors import SetupRequiredError

logger = logging.getLogger("seo_geo_agent.presence")

#: Cate rezultate se citesc pe intrebare. Motoarele generative pornesc de la
#: primele rezultate; peste 10, prezenta nu mai spune mare lucru.
DEFAULT_MAX_RESULTS = 10
#: Cate domenii "in locul tau" se intorc in raport.
TOP_COMPETING_DOMAINS = 10
SEARCH_TIMEOUT_SECONDS = 15.0

QuestionStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Un rezultat de cautare: titlu, adresa, fragment."""

    title: str
    url: str
    snippet: str = ""


class SearchProvider(Protocol):
    """Sursa rezultatelor. Implementarea reala e :class:`DuckDuckGoSearchProvider`."""

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]: ...


@dataclass(slots=True)
class QuestionPresence:
    """Rezultatul unei intrebari."""

    question: str
    status: QuestionStatus
    brand_mentioned: bool = False
    #: Pozitia (de la 1) primului rezultat de pe domeniul brandului; ``None`` = absent.
    own_domain_position: int | None = None
    result_domains: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class PresenceReport:
    """Raportul complet: pe intrebare si agregat."""

    brand: str
    domain: str
    questions: list[QuestionPresence]
    #: Din intrebarile la care cautarea a mers: in cate apare brandul (0-1).
    brand_presence_rate: float
    #: Din intrebarile la care cautarea a mers: in cate apare domeniul (0-1).
    own_domain_rate: float
    #: Domeniile care apar cel mai des in locul brandului, cu numarul de aparitii.
    competing_domains: list[tuple[str, int]]


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_own_domain(url: str, domain: str) -> bool:
    own = _host(domain if "//" in domain else f"https://{domain}")
    host = _host(url)
    return bool(own) and (host == own or host.endswith(f".{own}"))


def evaluate_question(
    question: str, hits: Sequence[SearchHit], *, brand: str, domain: str
) -> QuestionPresence:
    """Prezenta brandului intr-un set de rezultate (functie pura)."""
    own_position = next(
        (index for index, hit in enumerate(hits, start=1) if _is_own_domain(hit.url, domain)),
        None,
    )
    mentioned = own_position is not None or any(
        count_brand_mentions(f"{hit.title} {hit.snippet}", brand) > 0 for hit in hits
    )
    return QuestionPresence(
        question=question,
        status="ok",
        brand_mentioned=mentioned,
        own_domain_position=own_position,
        result_domains=[_host(hit.url) for hit in hits if _host(hit.url)],
    )


def evaluate_presence(
    brand: str, domain: str, questions: Sequence[QuestionPresence]
) -> PresenceReport:
    """Agregatul peste intrebari. Intrebarile picate nu intra in rate."""
    answered = [item for item in questions if item.status == "ok"]
    own = _host(domain if "//" in domain else f"https://{domain}")
    competitors: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for item in answered:
        # dict.fromkeys: o singura numarare pe intrebare, in ordinea rezultatelor.
        for host in dict.fromkeys(item.result_domains):
            if host == own or host.endswith(f".{own}"):
                continue
            competitors[host] += 1
            first_seen.setdefault(host, len(first_seen))
    # Ordine determinista: dupa frecventa, apoi dupa prima aparitie (pozitia in
    # cautare conteaza: primul rezultat e cel citat cel mai probabil).
    ranked = sorted(competitors.items(), key=lambda item: (-item[1], first_seen[item[0]]))
    total = len(answered)
    return PresenceReport(
        brand=brand,
        domain=domain,
        questions=list(questions),
        brand_presence_rate=(sum(item.brand_mentioned for item in answered) / total)
        if total
        else 0.0,
        own_domain_rate=(
            sum(item.own_domain_position is not None for item in answered) / total if total else 0.0
        ),
        competing_domains=ranked[:TOP_COMPETING_DOMAINS],
    )


async def probe_presence(
    brand: str,
    domain: str,
    questions: Sequence[str],
    provider: SearchProvider,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> PresenceReport:
    """Pune toate intrebarile in paralel si intoarce raportul.

    O intrebare picata (timeout, limita, retea) nu opreste testul: ramane in
    raport cu ``status="failed"`` si motivul, iar ratele se calculeaza doar din
    cele care au mers - un esec de retea nu e "brandul lipseste".
    """

    async def one(question: str) -> QuestionPresence:
        try:
            hits = await asyncio.wait_for(
                provider.search(question, max_results=max_results),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
        except SetupRequiredError:
            raise
        except Exception as exc:  # cautarea externa poate pica in orice fel
            logger.warning("cautare esuata pentru %r: %s", question, exc)
            return QuestionPresence(question=question, status="failed", error=str(exc)[:200])
        return evaluate_question(question, hits, brand=brand, domain=domain)

    results = await asyncio.gather(*(one(question) for question in questions))
    return evaluate_presence(brand, domain, results)


class DuckDuckGoSearchProvider:
    """Cautare reala prin ``ddgs`` (DuckDuckGo, fara cheie), regiunea Romania.

    Aceeasi biblioteca pe care o foloseste abilitatea ``web_search`` din
    ``ppc_agent_server`` - nu o importam de acolo, agentul asta e separat (vezi
    ``seo_geo_agent/__init__.py``).
    """

    def __init__(self, region: str = "ro-ro") -> None:
        self._region = region

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        try:
            from ddgs import DDGS
            from ddgs.exceptions import DDGSException
        except ImportError as exc:  # pragma: no cover - depinde de mediul instalat
            raise SetupRequiredError(
                "Testul de prezenta are nevoie de pachetul 'ddgs': "
                "pip install -r requirements-seo-geo.txt"
            ) from exc

        def run() -> list[dict[str, str]]:
            try:
                return list(
                    DDGS(timeout=int(SEARCH_TIMEOUT_SECONDS)).text(
                        query, region=self._region, max_results=max_results
                    )
                    or []
                )
            except DDGSException as exc:
                # ddgs semnaleaza "niciun rezultat" tot printr-o exceptie; pentru
                # testul de prezenta asta e un raspuns (brandul lipseste), nu un
                # esec de retea. Limitele si timeout-urile raman esecuri.
                if "no results" in str(exc).lower():
                    return []
                raise

        raw = await asyncio.to_thread(run)
        return [
            SearchHit(
                title=str(item.get("title") or ""),
                url=str(item.get("href") or item.get("url") or ""),
                snippet=str(item.get("body") or ""),
            )
            for item in raw
            if item.get("href") or item.get("url")
        ]
