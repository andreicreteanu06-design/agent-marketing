"""Pozitii in SERP pentru cuvinte ARBITRARE, via Serper.dev.

Singurul gol pe care sursele gratuite si oficiale nu-l acopera: Search Console
arata doar interogari pentru care site-ul a fost DEJA afisat, si doar pentru
site-ul propriu. Ca sa stim unde stam pe un cuvant pe care inca nu aparem - sau
unde sta un concurent - avem nevoie de o citire a SERP-ului.

De ce Serper.dev si nu un scraper propriu: un headless Chromium pe google.com
incalca termenii Google, se strica la fiecare schimbare de layout si ajunge in
CAPTCHA dupa cateva zeci de cereri, ceea ce ar cere proxy-uri rotative - adica
un cost mascat, plus fragilitate. Serper are un nivel gratuit si costa ~1$ la
1000 de interogari dupa. Clientul inca il poate inlocui: interfata
:class:`SerpProvider` exista exact ca o instanta SearXNG self-hosted (sau alt
furnizor) sa poata fi pusa in loc fara sa se schimbe nimic mai sus.

IMPORTANT: creditele sunt o resursa finita. Orice esec (fara cheie, credite
epuizate, retea) intoarce un rezultat marcat explicit, NU arunca in sus - o
verificare de pozitie ratata nu trebuie sa opreasca sincronizarea zilnica a
celorlalte cuvinte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("ppc_agent.search_data.serp_tracker")

_SERPER_URL = "https://google.serper.dev/search"
_DEFAULT_TIMEOUT = 20.0
#: Cate rezultate organice citim. 100 = prima "pagina" clasica extinsa; peste
#: pozitia 100 diferenta nu mai conteaza pentru nicio decizie.
_DEFAULT_DEPTH = 100
#: Cati concurenti retinem per interogare (cine ne-a luat-o inainte).
TOP_COMPETITORS = 3

SerpStatus = Literal["ok", "no_credits", "not_configured", "error"]


def registrable_domain(value: str) -> str:
    """Domeniul comparabil dintr-un URL sau host: fara schema, fara ``www.``, litere mici.

    Comparatia de domenii din SERP trebuie sa fie tolerantă la forma exacta:
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
    #: Prezenta unui AI Overview: pentru partea de GEO conteaza daca Google
    #: raspunde singur, fiindca atunci click-urile organice scad chiar si de pe 1.
    has_ai_overview: bool = False
    total_results_read: int = 0
    message: str = ""


class SerpProvider(Protocol):
    """Contractul minim al unei surse de SERP - implementabil si de SearXNG."""

    def check_ranking(self, keyword: str, domain: str) -> SerpCheck:
        """Pozitia lui ``domain`` pentru ``keyword``, plus concurentii de deasupra."""
        ...


class SerperSerpProvider:
    """Implementare peste API-ul Serper.dev."""

    def __init__(
        self,
        *,
        api_key: str = "",
        country: str = "ro",
        language: str = "ro",
        location: str = "",
        depth: int = _DEFAULT_DEPTH,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._country = country
        self._language = language
        self._location = location
        self._depth = depth
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        """``False`` = nicio cheie; apelantul poate sari peste verificari intregi."""
        return bool(self._api_key)

    def check_ranking(self, keyword: str, domain: str) -> SerpCheck:
        """Interogheaza SERP-ul o singura data si extrage ce ne trebuie.

        Nu arunca niciodata: orice problema devine un ``SerpCheck`` cu ``status``
        diferit de ``"ok"`` si un mesaj lizibil. Vezi docstring-ul modulului.
        """
        target = registrable_domain(domain)
        if not self._api_key:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="not_configured",
                message=(
                    "SERPER_API_KEY nu e setat - verificarea pozitiilor pentru cuvinte "
                    "arbitrare e dezactivata. Pozitiile din Search Console functioneaza "
                    "in continuare."
                ),
            )
        if not keyword.strip() or not target:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message="Cuvantul cheie sau domeniul lipseste.",
            )

        body: dict[str, Any] = {
            "q": keyword,
            "gl": self._country,
            "hl": self._language,
            "num": self._depth,
        }
        if self._location:
            body["location"] = self._location

        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(
                    _SERPER_URL,
                    headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message=f"Serper nu a raspuns in {self._timeout:.0f}s.",
            )
        except httpx.HTTPError as exc:
            return SerpCheck(
                keyword=keyword, domain=target, status="error", message=f"Serper inaccesibil: {exc}"
            )

        # 401/403 = cheie gresita sau revocata; 429 = credite epuizate sau prea
        # multe cereri. Le separam fiindca duc la actiuni diferite: una se
        # repara in setari, cealalta inseamna "asteapta sau cumpara credite".
        if response.status_code in (401, 403):
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="not_configured",
                message="Serper a refuzat cheia API (401/403). Verific-o in setari.",
            )
        if response.status_code == 429:
            logger.warning("Serper: credite epuizate sau rate limit atins")
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="no_credits",
                message=(
                    "Creditele Serper s-au terminat (sau ai atins limita de rata). "
                    "Verificarile de pozitie se reiau cand ai din nou credite."
                ),
            )
        if response.status_code >= 400:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message=f"Serper a raspuns {response.status_code}: {response.text[:150]}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            return SerpCheck(
                keyword=keyword,
                domain=target,
                status="error",
                message=f"Raspuns Serper invalid: {exc}",
            )
        return _parse_serper_payload(keyword, target, payload)


def _parse_serper_payload(keyword: str, target: str, payload: dict[str, Any]) -> SerpCheck:
    """Extrage pozitia proprie si primii concurenti din raspunsul Serper.

    Pozitia raportata e cea NUMARATA de noi peste rezultatele organice, nu
    campul ``position`` din raspuns: acela poate sari sau lipsi cand Google
    insereaza blocuri speciale, iar noi vrem "al catelea rezultat organic".
    """
    organic = payload.get("organic")
    if not isinstance(organic, list):
        return SerpCheck(
            keyword=keyword,
            domain=target,
            status="error",
            message="Raspunsul Serper nu contine rezultate organice.",
        )

    position: int | None = None
    found_url: str | None = None
    competitors: list[SerpCompetitor] = []

    for index, item in enumerate(organic, start=1):
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "")
        item_domain = registrable_domain(link)
        if not item_domain:
            continue
        if item_domain == target and position is None:
            position = index
            found_url = link
            continue
        # Concurentii ne intereseaza doar pana la pozitia noastra: cine e SUB
        # noi nu ne-a luat nimic.
        if position is None and len(competitors) < TOP_COMPETITORS:
            competitors.append(
                SerpCompetitor(
                    position=index,
                    domain=item_domain,
                    url=link,
                    title=str(item.get("title") or ""),
                )
            )

    return SerpCheck(
        keyword=keyword,
        domain=target,
        status="ok",
        position=position,
        url=found_url,
        competitors=competitors,
        # Serper expune AI Overview sub chei diferite in timp; acceptam ambele
        # in loc sa ne legam de una singura.
        has_ai_overview=bool(payload.get("aiOverview") or payload.get("answerBox")),
        total_results_read=len(organic),
    )
