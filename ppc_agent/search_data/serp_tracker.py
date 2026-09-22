"""Pozitii in SERP pentru cuvinte ARBITRARE, via OpenSERP self-hosted.

Singurul gol pe care sursele gratuite si oficiale nu-l acopera: Search Console
arata doar interogari pentru care site-ul a fost DEJA afisat, si doar pentru
site-ul propriu. Ca sa stim unde stam pe un cuvant pe care inca nu aparem - sau
unde sta un concurent - avem nevoie de o citire a SERP-ului.

Sursa e o instanta LOCALA de OpenSERP (https://github.com/karust/openserp),
nu un API comercial: zero cost recurent, zero cheie, zero vendor care poate
schimba preturile sau termenii. Compromisul, spus pe fata fiindca modeleaza
codul de mai jos: OpenSERP conduce un browser headless impotriva Google. E
acelasi scraping pe care un serviciu platit il face in locul tau, mutat pe
infrastructura ta - deci CAPTCHA-urile, blocarile de IP si stricaciunile la
fiecare schimbare de layout Google devin problema noastra. De aceea:

- nicio eroare nu arunca in sus: o verificare ratata produce un ``SerpCheck``
  cu status explicit, si sincronizarea celorlalte cuvinte continua;
- ``blocked`` e o stare de sine statatoare, distincta de ``error``: cand Google
  cere CAPTCHA, raspunsul corect nu e "reincearca imediat", ci "opreste-te";
- concurenta e deliberat MICA (:data:`DEFAULT_CONCURRENCY`) - a trage 20 de
  interogari deodata prin acelasi IP e cel mai rapid mod de a fi blocat.

:class:`SerpProvider` ramane un ``Protocol``: o instanta SearXNG self-hosted,
sau orice alta sursa, poate lua locul fara sa se schimbe nimic mai sus.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("ppc_agent.search_data.serp_tracker")

_DEFAULT_TIMEOUT = 60.0
#: Cate rezultate citim. 100 e maximul acceptat de OpenSERP intr-o cerere;
#: peste pozitia 100 diferenta nu mai conteaza pentru nicio decizie.
DEFAULT_DEPTH = 100
#: Cati concurenti retinem per interogare (cine ne-a luat-o inainte).
TOP_COMPETITORS = 3
#: Interogari simultane catre instanta locala. Mic intentionat - vezi docstring.
DEFAULT_CONCURRENCY = 2

#: Semne ca Google a servit o provocare in locul rezultatelor. OpenSERP le
#: raporteaza ca eroare text, nu cu un cod de stare dedicat.
_BLOCKED_MARKERS = ("captcha", "unusual traffic", "blocked", "rate limit", "too many requests")

SerpStatus = Literal["ok", "unavailable", "blocked", "error"]


def registrable_domain(value: str) -> str:
    """Domeniul comparabil dintr-un URL sau host: fara schema, fara ``www.``, litere mici.

    Comparatia de domenii din SERP trebuie sa fie toleranta la forma exacta:
    ``https://www.Exemplu.ro/pagina`` si ``exemplu.ro`` sunt acelasi site.
    Nu incercam sa rezolvam sufixele publice (``.co.uk``) - pentru potrivirea
    "e site-ul meu?" e suficient hostname-ul normalizat.
    """
    raw = value.strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = urlsplit(raw).hostname or ""
    return host.removeprefix("www.")


@dataclass(frozen=True, slots=True)
class SerpCompetitor:
    """Un rezultat organic care sta inaintea noastra."""

    position: int
    domain: str
    url: str
    title: str


@dataclass(frozen=True, slots=True)
class SerpCheck:
    """Rezultatul unei verificari de pozitie pentru o interogare.

    ``position is None`` cu ``status="ok"`` inseamna un raspuns valid in care
    domeniul nu apare in primele ``depth`` rezultate - o informatie reala
    ("nu ranchezi"), nu o eroare. Distinctia asta e motivul pentru care
    ``status`` exista separat de ``position``.
    """

    keyword: str
    domain: str
    status: SerpStatus
    position: int | None = None
    url: str | None = None
    competitors: list[SerpCompetitor] = field(default_factory=list)
    total_results_read: int = 0
    message: str = ""


class SerpProvider(Protocol):
    """Contractul minim al unei surse de SERP - implementabil si de SearXNG."""

    async def check_ranking(self, keyword: str, domain: str) -> SerpCheck:
        """Pozitia lui ``domain`` pentru ``keyword``, plus concurentii de deasupra."""
        ...


class OpenSerpProvider:
    """Client pentru o instanta locala de OpenSERP.

    Pornirea instantei (vezi README, sectiunea despre urmarirea pozitiilor)::

        docker run --rm -p 127.0.0.1:7000:7000 karust/openserp:latest serve -a 0.0.0.0 -p 7000

    Fara instanta pornita, :meth:`check_ranking` intoarce ``status="unavailable"``
    cu un mesaj care spune exact asta - restul platformei (pozitiile reale din
    Search Console, analizele incrucisate) functioneaza neschimbat.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:7000",
        engine: str = "google",
        language: str = "RO",
        region: str = "RO",
        depth: int = DEFAULT_DEPTH,
        timeout: float = _DEFAULT_TIMEOUT,
        concurrency: int = DEFAULT_CONCURRENCY,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._engine = engine
        self._language = language
        self._region = region
        self._depth = depth
        self._timeout = timeout
        self._concurrency = max(1, concurrency)
        self._transport = transport

    @property
    def base_url(self) -> str:
        """Adresa instantei interogate."""
        return self._base_url

    def _params(self, keyword: str) -> dict[str, Any]:
        return {
            "text": keyword,
            "lang": self._language,
            "region": self._region,
            "limit": self._depth,
        }

    async def check_ranking(self, keyword: str, domain: str) -> SerpCheck:
        """Verifica o singura interogare. Nu arunca niciodata - vezi docstring-ul modulului."""
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            return await self._check_with(client, keyword, domain)

    async def check_rankings(self, keywords: Sequence[str], domain: str) -> list[SerpCheck]:
        """Verifica mai multe interogari refolosind aceeasi conexiune.

        Concurenta e plafonata de ``concurrency`` (implicit 2): instanta e
        locala, dar cererile ies tot spre Google printr-un singur IP, iar o
        rafala e cel mai rapid mod de a primi CAPTCHA. Rezultatele pastreaza
        ordinea din ``keywords``.
        """
        if not keywords:
            return []
        semaphore = asyncio.Semaphore(self._concurrency)
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:

            async def one(keyword: str) -> SerpCheck:
                async with semaphore:
                    return await self._check_with(client, keyword, domain)

            return list(await asyncio.gather(*(one(keyword) for keyword in keywords)))

    async def _check_with(
        self, client: httpx.AsyncClient, keyword: str, domain: str
    ) -> SerpCheck:
        target = registrable_domain(domain)
        if not keyword.strip() or not target:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message="Cuvantul cheie sau domeniul lipseste.",
            )

        url = f"{self._base_url}/{self._engine}/search"
        try:
            response = await client.get(url, params=self._params(keyword))
        except httpx.TimeoutException:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="unavailable",
                message=(
                    f"OpenSERP nu a raspuns in {self._timeout:.0f}s. Un browser headless "
                    "poate dura la interogari grele; daca se repeta, creste timeout-ul."
                ),
            )
        except httpx.HTTPError:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="unavailable",
                message=(
                    f"Nu pot contacta OpenSERP la {self._base_url}. Porneste instanta: "
                    "docker run --rm -p 127.0.0.1:7000:7000 karust/openserp:latest "
                    "serve -a 0.0.0.0 -p 7000"
                ),
            )

        if response.status_code == 429 or _looks_blocked(response.text):
            logger.warning("OpenSERP: Google a blocat interogarea '%s'", keyword)
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="blocked",
                message=(
                    "Google a cerut verificare anti-bot (CAPTCHA sau limitare de rata). "
                    "Opreste verificarile pentru o vreme - reincercarea imediata "
                    "inrautateste blocarea."
                ),
            )
        if response.status_code >= 400:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message=f"OpenSERP a raspuns {response.status_code}: {response.text[:150]}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message=f"Raspuns OpenSERP invalid: {exc}",
            )
        return _parse_results(keyword, target, payload)


def _looks_blocked(body: str) -> bool:
    """``True`` cand corpul raspunsului tradeaza o provocare anti-bot."""
    snippet = body[:2000].lower()
    return any(marker in snippet for marker in _BLOCKED_MARKERS)


def _extract_rows(payload: Any) -> list[dict[str, Any]] | None:
    """Scoate lista de rezultate, acceptand ambele forme pe care le poate lua.

    OpenSERP intoarce de obicei un array JSON la radacina, dar variantele mai
    noi il pot infasura intr-un obiect (``{"results": [...]}``). Acceptam
    ambele in loc sa ne legam de una si sa cadem tacut la un upgrade.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("results", "organic", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return None


def _parse_results(keyword: str, target: str, payload: Any) -> SerpCheck:
    """Gaseste pozitia proprie si concurentii de deasupra, in rezultatele citite.

    Pozitia raportata e cea NUMARATA de noi peste rezultatele organice, nu
    campul ``rank`` din raspuns: acela reflecta pozitia din pagina Google, care
    include blocuri non-organice si poate sari. Noi vrem "al catelea rezultat
    organic", fiindca asta se compara cu pozitia medie din Search Console.
    """
    rows = _extract_rows(payload)
    if rows is None:
        return SerpCheck(
            keyword=keyword,
            domain=target,
            status="error",
            message="Raspunsul OpenSERP nu contine o lista de rezultate.",
        )

    position: int | None = None
    found_url: str | None = None
    competitors: list[SerpCompetitor] = []
    organic_index = 0

    for row in rows:
        # OpenSERP eticheteaza rezultatele; cand tipul lipseste (versiuni mai
        # vechi), presupunem organic - altfel n-am numara nimic.
        row_type = str(row.get("type") or "organic").lower()
        if row_type != "organic":
            continue
        link = str(row.get("url") or "")
        row_domain = registrable_domain(str(row.get("domain") or "") or link)
        if not row_domain:
            continue

        organic_index += 1
        if row_domain == target and position is None:
            position = organic_index
            found_url = link
            continue
        # Concurentii ne intereseaza doar pana la pozitia noastra: cine e SUB
        # noi nu ne-a luat nimic.
        if position is None and len(competitors) < TOP_COMPETITORS:
            competitors.append(
                SerpCompetitor(
                    position=organic_index,
                    domain=row_domain,
                    url=link,
                    title=str(row.get("title") or ""),
                )
            )

    return SerpCheck(
        keyword=keyword,
        domain=target,
        status="ok",
        position=position,
        url=found_url,
        competitors=competitors,
        total_results_read=organic_index,
    )


def check_rankings_sync(
    provider: OpenSerpProvider, keywords: Sequence[str], domain: str
) -> list[SerpCheck]:
    """Puntea catre stratul SINCRON de joburi (``ppc_agent_server/jobs/tasks.py``).

    Providerul e async fiindca verificarea a 100 de cuvinte beneficiaza de
    concurenta (marginita), dar joburile serverului sunt functii sincrone.
    Functia asta e singurul loc unde se face traducerea - de evitat apelarea ei
    dintr-o bucla de evenimente deja pornita (``asyncio.run`` ar crapa acolo);
    in cod async, apeleaza direct ``provider.check_rankings``.
    """
    return asyncio.run(provider.check_rankings(keywords, domain))
