"""Google Search Console: pozitiile REALE ale site-ului in cautarea Google.

De ce asta si nu un rank tracker care scrapeaza SERP-ul: datele de aici sunt
masurate de Google pe traficul real al site-ului - pozitie medie, afisari,
click-uri, CTR, per interogare, pagina, tara si dispozitiv. Un scraper vede o
singura fotografie a SERP-ului, dintr-o singura locatie, pentru un utilizator
care nu exista; GSC vede ce au vazut oamenii care chiar au cautat.

Limitele, spuse pe fata, fiindca modeleaza tot ce construim peste:

- doar site-ul PROPRIU (verificat in Search Console). Pozitiile concurentilor
  nu se pot obtine de aici, cu niciun truc;
- doar interogari pentru care site-ul a fost DEJA afisat. Un cuvant pe care nu
  aparem inca nu exista in GSC - de aceea golurile se detecteaza incrucisat, din
  termenii de cautare platiti (vezi ``insights.py``);
- 16 luni de istoric, apoi Google sterge definitiv. De asta importam zilnic
  intr-o tabela proprie: istoricul nostru creste dincolo de fereastra lor;
- 25.000 de randuri pe cerere, 50.000 pe zi per site si tip de cautare;
- ultimele ~2-3 zile sunt incomplete (``dataState="final"`` le exclude).

API: ``POST /webmasters/v3/sites/{siteUrl}/searchAnalytics/query``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.search_data.google_oauth import SEARCH_CONSOLE_SCOPE, exchange_refresh_token

_BASE_URL = "https://www.googleapis.com/webmasters/v3"
_DEFAULT_TIMEOUT = 30.0
#: Maximul acceptat de API intr-o singura cerere.
_ROWS_PER_REQUEST = 25_000
#: Plafonul zilnic per site, dupa documentatia Google. Ne oprim singuri inainte
#: sa-l atingem, ca importul de maine sa nu inceapa cu o cota deja consumata.
_MAX_ROWS_PER_SYNC = 50_000

#: Dimensiunile pe care le cerem. ``date`` e prima ca randurile sa vina deja
#: grupate pe zi - importul e incremental, pe zile, nu pe agregat.
DEFAULT_DIMENSIONS = ("date", "query", "page", "country", "device")


@dataclass(frozen=True, slots=True)
class SearchAnalyticsRow:
    """Un rand din Search Console: o interogare, intr-o zi, pe o pagina."""

    day: date
    query: str
    page: str
    country: str
    device: str
    clicks: int
    impressions: int
    ctr: float
    #: Pozitia MEDIE pentru acea zi (1.0 = primul rezultat). Zecimala, nu
    #: intreaga: o pozitie de 3.4 inseamna ca uneori am fost 3, uneori 4.
    position: float


@dataclass(frozen=True, slots=True)
class QueryTotals:
    """O interogare, agregata pe tot intervalul cerut.

    Distinct de :class:`SearchAnalyticsRow`, care e per ZI: aici Google a facut
    deja insumarea si media. Conteaza, fiindca ``position`` nu se poate media
    corect in Python din randuri zilnice fara sa ponderezi dupa afisari - iar
    API-ul o face oricum mai bine, ca are datele brute.
    """

    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass(frozen=True, slots=True)
class QueryPageTotals:
    """O interogare pe o pagina, agregata pe tot intervalul cerut."""

    query: str
    page: str
    clicks: int
    impressions: int
    position: float


def normalize_site_url(raw: str) -> str:
    """Aduce identificatorul proprietatii la forma ceruta de API.

    Search Console are doua tipuri de proprietati si le trateaza diferit:
    ``sc-domain:exemplu.ro`` (domeniu, acopera toate subdomeniile si schemele)
    si ``https://exemplu.ro/`` (prefix URL). Acceptam ce scrie clientul si
    completam ce lipseste, in loc sa-i cerem sa stie distinctia.
    """
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("sc-domain:"):
        return value
    if value.startswith(("http://", "https://")):
        return value if value.endswith("/") else f"{value}/"
    # Un domeniu simplu ("exemplu.ro") e cel mai probabil o proprietate de tip
    # domeniu - forma care acopera si www, si http, si https.
    return f"sc-domain:{value}"


class SearchConsoleClient:
    """Client de citire pentru Search Console Search Analytics."""

    def __init__(
        self,
        *,
        site_url: str,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._site_url = normalize_site_url(site_url)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._transport = transport
        self._cached_access_token: str | None = None

    @property
    def site_url(self) -> str:
        """Proprietatea interogata, in forma normalizata ceruta de API."""
        return self._site_url

    def _access_token(self) -> str:
        if self._cached_access_token is None:
            self._cached_access_token = exchange_refresh_token(
                client_id=self._client_id,
                client_secret=self._client_secret,
                refresh_token=self._refresh_token,
                timeout=self._timeout,
                transport=self._transport,
                missing_message=(
                    "Conectarea la Search Console e incompleta: lipsesc client_id/"
                    "client_secret/refresh_token. Refresh token-ul trebuie generat cu "
                    f"scope-ul {SEARCH_CONSOLE_SCOPE} - cel de Google Ads NU e valabil aici."
                ),
            )
        return self._cached_access_token

    def _post_query(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self._site_url:
            raise SetupRequiredError(
                "Proprietatea Search Console nu e setata pentru acest client "
                "(ex. 'sc-domain:exemplu.ro')."
            )
        # Proprietatile de tip domeniu contin ':' - trebuie codificat in cale,
        # altfel API-ul vede o ruta care nu exista si raspunde 404.
        quoted_site = self._site_url.replace(":", "%3A").replace("/", "%2F")
        url = f"{_BASE_URL}/sites/{quoted_site}/searchAnalytics/query"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token()}",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.ConnectError as exc:
            raise SetupRequiredError("Search Console API nu raspunde.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Search Console API nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        if response.status_code == 403:
            raise SetupRequiredError(
                f"Search Console refuza accesul la '{self._site_url}'. Verifica daca "
                "proprietatea e verificata pe contul care a emis refresh token-ul."
            )
        if response.status_code == 404:
            raise SetupRequiredError(
                f"Search Console nu gaseste proprietatea '{self._site_url}'. Scrie-o exact "
                "ca in interfata (ex. 'sc-domain:exemplu.ro' sau 'https://exemplu.ro/')."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Search Console API a raspuns {response.status_code}: {response.text[:200]}"
            )
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns Search Console invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("raspuns Search Console invalid: nu e un obiect JSON")
        return payload


    def fetch_search_analytics(
        self,
        *,
        start_date: date,
        end_date: date,
        dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
        search_type: str = "web",
        max_rows: int = _MAX_ROWS_PER_SYNC,
    ) -> list[SearchAnalyticsRow]:
        """Randurile de performanta din intervalul cerut, paginate pana la ``max_rows``.

        ``dataState`` ramane implicit (``"final"``): Google marcheaza ultimele
        zile ca provizorii, iar daca le-am importa ca definitive am scrie in
        istoric cifre care se mai schimba.
        """
        rows: list[SearchAnalyticsRow] = []
        start_row = 0
        while len(rows) < max_rows:
            limit = min(_ROWS_PER_REQUEST, max_rows - len(rows))
            payload = self._post_query(
                {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "dimensions": list(dimensions),
                    "type": search_type,
                    "rowLimit": limit,
                    "startRow": start_row,
                }
            )
            batch = payload.get("rows") or []
            rows.extend(_parse_rows(batch, dimensions))
            # Mai putine randuri decat am cerut = am ajuns la capatul datelor.
            if len(batch) < limit:
                break
            start_row += len(batch)
        return rows


    def fetch_query_totals(
        self,
        *,
        start_date: date,
        end_date: date,
        max_rows: int = _ROWS_PER_REQUEST,
    ) -> list[QueryTotals]:
        """Interogarile organice ale intervalului, agregate de Google.

        Args:
            start_date: Prima zi inclusa.
            end_date: Ultima zi inclusa.
            max_rows: Plafon de interogari returnate.

        Returns:
            Lista de :class:`QueryTotals`, in ordinea data de API (descrescator
            dupa click-uri).

        O singura cerere in loc de ``fetch_search_analytics`` cu dimensiunea
        ``date``: cand nu ai nevoie de istoric zilnic, agregarea pe server e si
        mai ieftina, si mai corecta.
        """
        payload = self._post_query(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query"],
                "type": "web",
                "rowLimit": min(_ROWS_PER_REQUEST, max_rows),
            }
        )
        totals: list[QueryTotals] = []
        for raw in payload.get("rows") or []:
            if not isinstance(raw, dict):
                continue
            keys = raw.get("keys") or []
            if len(keys) != 1:
                continue
            totals.append(
                QueryTotals(
                    query=str(keys[0]),
                    clicks=int(raw.get("clicks", 0)),
                    impressions=int(raw.get("impressions", 0)),
                    ctr=float(raw.get("ctr", 0.0)),
                    position=float(raw.get("position", 0.0)),
                )
            )
        return totals


    def fetch_query_pages(
        self,
        *,
        start_date: date,
        end_date: date,
        max_rows: int = 1000,
    ) -> list[QueryPageTotals]:
        """Interogarile intervalului pe pagina care a aparut pentru ele.

        Agregate de Google pe perechea (interogare, pagina) - asa se afla CE
        pagina trebuie rescrisa cand un cuvant are CTR mic.
        """
        payload = self._post_query(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query", "page"],
                "type": "web",
                "rowLimit": min(_ROWS_PER_REQUEST, max_rows),
            }
        )
        rows: list[QueryPageTotals] = []
        for raw in payload.get("rows") or []:
            if not isinstance(raw, dict):
                continue
            keys = raw.get("keys") or []
            if len(keys) != 2:
                continue
            rows.append(
                QueryPageTotals(
                    query=str(keys[0]),
                    page=str(keys[1]),
                    clicks=int(raw.get("clicks", 0)),
                    impressions=int(raw.get("impressions", 0)),
                    position=float(raw.get("position", 0.0)),
                )
            )
        return rows


def _parse_rows(
    raw_rows: list[dict[str, Any]], dimensions: tuple[str, ...]
) -> list[SearchAnalyticsRow]:
    """Transforma raspunsul API in randuri tipizate, sarind peste ce e malformat.

    API-ul intoarce dimensiunile ca lista pozitionala in ``keys``, in ordinea
    ceruta - de aici maparea dupa index. Un rand caruia ii lipsesc cheile nu
    opreste importul: pierdem un rand, nu sincronizarea intreaga.
    """
    parsed: list[SearchAnalyticsRow] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        keys = raw.get("keys") or []
        if len(keys) != len(dimensions):
            continue
        values = dict(zip(dimensions, keys, strict=True))
        raw_day = values.get("date", "")
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            continue
        parsed.append(
            SearchAnalyticsRow(
                day=day,
                query=values.get("query", ""),
                page=values.get("page", ""),
                country=values.get("country", ""),
                device=values.get("device", ""),
                clicks=int(raw.get("clicks", 0)),
                impressions=int(raw.get("impressions", 0)),
                ctr=float(raw.get("ctr", 0.0)),
                position=float(raw.get("position", 0.0)),
            )
        )
    return parsed
