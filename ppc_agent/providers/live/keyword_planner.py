"""Furnizor live pentru Google Keyword Planner (Modulul 1).

Ruleaza peste ``KeywordPlanIdeaService.GenerateKeywordIdeas`` din Google Ads
API, prin REST (``httpx``), ca restul furnizorilor live - fara SDK-ul gRPC.

**Volumele exacte cer cheltuiala activa.** Un cont Google Ads fara istoric de
cheltuiala primeste de la API intervale largi (``0-10``, ``100-1K``), nu numere.
Nu compensam cu estimari proprii: cifra care ajunge in raport e cea de la
Google sau niciuna.

Constantele de limba si de tara NU sunt scrise de mana aici. Id-urile Google
pentru limbi nu se deduc din codul ISO (``ro`` nu e ``1038`` prin vreo regula,
ci prin tabelul lor), iar o constanta gresita intoarce tacut volume pentru alta
limba - exact genul de eroare pe care n-ai cum s-o observi din raport. Deci le
cerem de la API (``language_constant``/``geo_target_constant``) si le tinem in
cache pe durata instantei.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import KeywordPlannerProvider
from ppc_agent.search_data.google_oauth import exchange_refresh_token

logger = logging.getLogger("ppc_agent.providers.live.keyword_planner")

_API_VERSION = "v25"  # Aceeasi versiune ca in google_ads.py - bump-uite impreuna.
_BASE_URL = f"https://googleads.googleapis.com/{_API_VERSION}"
_DEFAULT_TIMEOUT = 30.0

_MISSING_CREDENTIALS = (
    "PPC_GOOGLE_ADS_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN lipsesc - "
    "completeaza-le in .env pentru Keyword Planner live."
)

#: Cat de multe idei cerem. API-ul intoarce mult peste ce foloseste Modulul 1.
_MAX_IDEAS = 1000

#: Mijlocul fiecarei galeti de competitie, pentru cand API-ul da doar eticheta,
#: nu si indexul 0-100. Documentate de Google ca LOW [0,33], MEDIUM [34,66],
#: HIGH [67,100] - luam mijlocul, si o spunem, in loc sa pretindem precizie.
_COMPETITION_BUCKETS = {"LOW": 0.17, "MEDIUM": 0.5, "HIGH": 0.84}

#: Peste acest prag de competitie sugeram ``phrase`` in loc de ``exact``.
#: Regula e A NOASTRA, nu a Google: API-ul nu sugereaza tipuri de potrivire.
#: Acelasi prag ca in furnizorul ``mock``, ca cele doua moduri sa nu dea
#: recomandari diferite pe aceleasi cifre.
_PHRASE_ABOVE_COMPETITION = 0.5

_COLUMNS = [
    "keyword",
    "avg_monthly_searches",
    "competition",
    "low_top_bid",
    "high_top_bid",
    "match_type_suggestion",
]


def _micros_to_currency(raw: Any) -> float:
    """Micro-unitatile Google in unitati de moneda. Lipsa inseamna 0, nu eroare."""
    try:
        return round(int(raw) / 1_000_000, 2)
    except (TypeError, ValueError):
        return 0.0


class LiveKeywordPlannerProvider(KeywordPlannerProvider):
    """Expansiune reala de cuvinte cheie, din Google Ads.

    Args:
        developer_token: Token-ul de dezvoltator Google Ads.
        client_id: Client ID-ul OAuth.
        client_secret: Client secret-ul OAuth.
        refresh_token: Refresh token cu scope ``adwords``.
        customer_id: Contul in numele caruia se cer ideile.
        login_customer_id: Doar cand contul se acceseaza printr-un MCC.
        timeout: Secunde pana la abandonarea unei cereri.
        transport: Injectat in teste; ``None`` in productie.
    """

    def __init__(
        self,
        *,
        developer_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        customer_id: str = "",
        login_customer_id: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._developer_token = developer_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._customer_id = customer_id
        self._login_customer_id = login_customer_id
        self._timeout = timeout
        self._transport = transport
        self._cached_access_token: str | None = None
        self._constant_cache: dict[str, str] = {}

    def _access_token(self) -> str:
        if self._cached_access_token is None:
            self._cached_access_token = exchange_refresh_token(
                client_id=self._client_id,
                client_secret=self._client_secret,
                refresh_token=self._refresh_token,
                timeout=self._timeout,
                transport=self._transport,
                missing_message=_MISSING_CREDENTIALS,
            )
        return self._cached_access_token

    def _headers(self) -> dict[str, str]:
        if not self._developer_token:
            raise SetupRequiredError(
                "PPC_GOOGLE_ADS_DEVELOPER_TOKEN lipseste - completeaza-l in .env."
            )
        if not self._customer_id:
            raise SetupRequiredError(
                "customer_id lipseste - seteaza PPC_GOOGLE_ADS_CUSTOMER_ID in .env."
            )
        headers = {
            "Content-Type": "application/json",
            "developer-token": self._developer_token,
            "Authorization": f"Bearer {self._access_token()}",
        }
        if self._login_customer_id:
            headers["login-customer-id"] = self._login_customer_id
        return headers

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{_BASE_URL}/customers/{self._customer_id}{path}"
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(url, headers=self._headers(), json=body)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Google Ads API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Google Ads API nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        if response.status_code in (401, 403):
            raise SetupRequiredError(
                f"Google Ads API a refuzat autentificarea ({response.status_code}): "
                f"{response.text[:200]}. Verifica developer_token/refresh_token/"
                "login_customer_id si permisiunile contului."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Google Ads API a raspuns {response.status_code}: {response.text[:200]}"
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns Google Ads invalid: {exc}") from exc
        return payload

    def _lookup_constant(self, cache_key: str, query: str, field: str) -> str:
        """Prima valoare a lui ``field`` pentru ``query``, cautata prin GAQL."""
        if cache_key in self._constant_cache:
            return self._constant_cache[cache_key]
        payload = self._post("/googleAds:search", {"query": query})
        for row in payload.get("results") or []:
            resource_name = (row.get(field) or {}).get("resourceName")
            if resource_name:
                self._constant_cache[cache_key] = str(resource_name)
                return str(resource_name)
        raise SetupRequiredError(
            f"Google Ads nu cunoaste '{cache_key}'. Verifica in .env codul de "
            "tara (PPC_GEO) si de limba (PPC_LANGUAGE) - trebuie sa fie coduri "
            "reale, ex. 'RO' si 'ro'."
        )

    def _language_resource(self, language: str) -> str:
        code = language.strip().lower()
        return self._lookup_constant(
            f"limba:{code}",
            "SELECT language_constant.resource_name FROM language_constant "
            f"WHERE language_constant.code = '{code}'",
            "languageConstant",
        )

    def _geo_resource(self, geo: str) -> str:
        code = geo.strip().upper()
        return self._lookup_constant(
            f"tara:{code}",
            "SELECT geo_target_constant.resource_name FROM geo_target_constant "
            f"WHERE geo_target_constant.country_code = '{code}' "
            "AND geo_target_constant.target_type = 'Country'",
            "geoTargetConstant",
        )

    def expand(self, seeds: list[str], geo: str, language: str) -> pd.DataFrame:
        """Extinde ``seeds`` in idei de cuvinte cheie cu volume si licitatii.

        Args:
            seeds: Cuvintele de pornire (din Search Console + crawling).
            geo: Cod de tara ISO (ex. ``RO``).
            language: Cod de limba ISO (ex. ``ro``).

        Returns:
            ``DataFrame`` cu ``keyword``, ``avg_monthly_searches``,
            ``competition``, ``low_top_bid``, ``high_top_bid``,
            ``match_type_suggestion``.

        Raises:
            SetupRequiredError: credentiale lipsa, cont fara acces, sau cod de
                tara/limba pe care Google nu-l recunoaste.
            ProviderError: raspuns neasteptat de la API.

        O lista goala de seminte intoarce un tabel gol, fara sa cheme API-ul:
        ``GenerateKeywordIdeas`` refuza cererile fara samanta, iar un 400 aici
        ar arata ca o defectiune, cand de fapt n-aveam ce cere.
        """
        clean_seeds = [seed.strip() for seed in seeds if seed.strip()]
        if not clean_seeds:
            logger.info("nicio samanta de extins - sar peste apelul Keyword Planner")
            return pd.DataFrame([], columns=_COLUMNS)

        payload = self._post(
            ":generateKeywordIdeas",
            {
                "keywordSeed": {"keywords": clean_seeds},
                "geoTargetConstants": [self._geo_resource(geo)],
                "language": self._language_resource(language),
                "keywordPlanNetwork": "GOOGLE_SEARCH",
                "pageSize": _MAX_IDEAS,
            },
        )

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in payload.get("results") or []:
            keyword = str(result.get("text", "")).strip()
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            metrics = result.get("keywordIdeaMetrics") or {}
            competition = _competition_of(metrics)
            rows.append(
                {
                    "keyword": keyword,
                    "avg_monthly_searches": int(metrics.get("avgMonthlySearches") or 0),
                    "competition": competition,
                    "low_top_bid": _micros_to_currency(metrics.get("lowTopOfPageBidMicros")),
                    "high_top_bid": _micros_to_currency(metrics.get("highTopOfPageBidMicros")),
                    "match_type_suggestion": (
                        "phrase" if competition >= _PHRASE_ABOVE_COMPETITION else "exact"
                    ),
                }
            )
        return pd.DataFrame(rows, columns=_COLUMNS)


def _competition_of(metrics: dict[str, Any]) -> float:
    """Competitia ca numar intre 0 si 1.

    Preferam ``competitionIndex`` (0-100, exact) si cadem pe mijlocul galetii
    doar cand lipseste. Un cont fara cheltuiala primeste deseori doar eticheta.
    """
    raw_index = metrics.get("competitionIndex")
    if raw_index is not None:
        try:
            return round(min(100, max(0, int(raw_index))) / 100.0, 2)
        except (TypeError, ValueError):
            pass
    label = str(metrics.get("competition", "")).upper()
    return _COMPETITION_BUCKETS.get(label, 0.0)
