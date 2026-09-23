"""Furnizor live pentru Google Business Profile (Modulul 1).

Doua API-uri, fiindca Google le-a spart in 2022 si nu le-a reunit:

- **Business Information** (``mybusinessbusinessinformation.googleapis.com/v1``)
  pentru nume si categorii;
- **Google My Business v4** (``mybusiness.googleapis.com/v4``) pentru recenzii.
  Numele e vechi si o parte din resursele lui sunt depreciate, dar ``reviews``
  NU e printre ele - e singura cale programatica spre recenzii si in 2026.

**Accesul cere aprobare de la Google.** Spre deosebire de Search Console sau
Ads, API-urile Business Profile nu se activeaza singur din consola: se cere
"Basic API Access" pentru proiect, iar raspunsul vine in 7-10 zile lucratoare.
Pana atunci cererile primesc 403, iar furnizorul o spune ca atare in loc sa
para o eroare de configurare pe care ai putea-o repara singur.

Sentimentul recenziilor se calculeaza local, cu
:func:`~ppc_agent.texttools.score_sentiment` - aceeasi functie ca in furnizorul
``mock``, deci cele doua moduri nu pot da scoruri diferite pe acelasi text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import GbpProvider
from ppc_agent.search_data.google_oauth import exchange_refresh_token
from ppc_agent.texttools import score_sentiment

logger = logging.getLogger("ppc_agent.providers.live.gbp")

_INFO_BASE_URL = "https://mybusinessbusinessinformation.googleapis.com/v1"
_REVIEWS_BASE_URL = "https://mybusiness.googleapis.com/v4"
_DEFAULT_TIMEOUT = 30.0

#: Cate pagini de recenzii citim. 50 pe pagina * 10 = 500 de recenzii, mai mult
#: decat are nevoie un scor de sentiment agregat.
_MAX_REVIEW_PAGES = 10
_REVIEWS_PER_PAGE = 50

_MISSING_CREDENTIALS = (
    "PPC_GOOGLE_OAUTH_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN lipsesc - "
    "completeaza-le in .env pentru Business Profile live. Consimtamantul "
    "trebuie sa includa scope-ul 'business.manage'."
)

_ACCESS_PENDING_HINT = (
    "Google a refuzat accesul la Business Profile. Spre deosebire de celelalte "
    "API-uri Google, astea cer 'Basic API Access' aprobat explicit pentru "
    "proiect (cerere la Google, raspuns in 7-10 zile lucratoare). Verifica si "
    "ca refresh token-ul acopera scope-ul 'business.manage'."
)

#: Nota in stele vine ca enum, nu ca numar.
_STAR_RATINGS = {"ONE": 1.0, "TWO": 2.0, "THREE": 3.0, "FOUR": 4.0, "FIVE": 5.0}

_LOCATION_PATTERN = re.compile(r"locations/([^/]+)")
_ACCOUNT_PATTERN = re.compile(r"accounts/([^/]+)")


def split_location_ref(raw: str, *, fallback_account_id: str = "") -> tuple[str, str]:
    """Desparte o referinta de locatie in (account_id, location_id).

    Args:
        raw: ``accounts/1/locations/2``, ``locations/2`` sau doar ``2``.
        fallback_account_id: Folosit cand ``raw`` nu contine contul.

    Returns:
        Perechea ``(account_id, location_id)``; ``account_id`` poate fi gol.

    Acceptam toate trei formele fiindca Google insusi le amesteca: Business
    Information lucreaza cu ``locations/{id}``, iar API-ul de recenzii cere
    ``accounts/{a}/locations/{l}``.
    """
    value = raw.strip()
    account_match = _ACCOUNT_PATTERN.search(value)
    location_match = _LOCATION_PATTERN.search(value)
    account_id = account_match.group(1) if account_match else fallback_account_id
    location_id = location_match.group(1) if location_match else value
    return account_id, location_id


class LiveGbpProvider(GbpProvider):
    """Semnale locale reale: nume, categorii, recenzii si sentimentul lor.

    Args:
        account_id: Contul Business Profile (necesar pentru recenzii).
        location_id: Locatia configurata de client. Gol = se foloseste
            argumentul primit de :meth:`local_signals`.
        client_id: Client ID-ul OAuth.
        client_secret: Client secret-ul OAuth.
        refresh_token: Refresh token cu scope ``business.manage``.
        timeout: Secunde pana la abandonarea unei cereri.
        transport: Injectat in teste; ``None`` in productie.
    """

    def __init__(
        self,
        *,
        account_id: str = "",
        location_id: str = "",
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._account_id = account_id
        self._location_id = location_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._transport = transport
        self._cached_access_token: str | None = None

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

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.get(url, headers=headers, params=params)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Business Profile nu raspunde la {url}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Business Profile nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        if response.status_code in (401, 403):
            raise SetupRequiredError(
                f"{_ACCESS_PENDING_HINT} (raspuns {response.status_code}: "
                f"{response.text[:160]})"
            )
        if response.status_code == 404:
            raise SetupRequiredError(
                f"Business Profile nu gaseste resursa ceruta ({url}). Verifica "
                "id-ul locatiei si al contului."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Business Profile a raspuns {response.status_code}: {response.text[:200]}"
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns Business Profile invalid: {exc}") from exc
        return payload

    def _business_info(self, location_id: str) -> tuple[str, list[str]]:
        """Numele si categoriile locatiei."""
        payload = self._get(
            f"{_INFO_BASE_URL}/locations/{location_id}",
            {"readMask": "title,categories"},
        )
        categories_block = payload.get("categories") or {}
        names: list[str] = []
        primary = (categories_block.get("primaryCategory") or {}).get("displayName")
        if primary:
            names.append(str(primary))
        for extra in categories_block.get("additionalCategories") or []:
            display = extra.get("displayName")
            if display:
                names.append(str(display))
        return str(payload.get("title", "")), names

    def _reviews(
        self, account_id: str, location_id: str
    ) -> tuple[list[dict[str, Any]], float, int]:
        """Recenziile, nota medie si numarul total raportat de Google."""
        url = f"{_REVIEWS_BASE_URL}/accounts/{account_id}/locations/{location_id}/reviews"
        collected: list[dict[str, Any]] = []
        average = 0.0
        total = 0
        page_token: str | None = None

        for _ in range(_MAX_REVIEW_PAGES):
            params: dict[str, Any] = {"pageSize": _REVIEWS_PER_PAGE}
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(url, params)
            # Google raporteaza totalul si media pe INTREAGA locatie, nu pe
            # pagina - le luam de la el, nu le recalculam din esantion.
            average = float(payload.get("averageRating") or average)
            total = int(payload.get("totalReviewCount") or total)
            collected.extend(payload.get("reviews") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        return collected, average, total

    def local_signals(self, location_id: str) -> dict[str, object]:
        """Numele, categoriile, recenziile si sentimentul lor pentru o locatie.

        Args:
            location_id: Locatia, daca nu e deja configurata pe furnizor.

        Returns:
            Dictionar cu ``name``, ``categories``, ``review_count``,
            ``avg_rating`` si ``reviews`` (fiecare cu ``text``/``score``/``label``).

        Raises:
            SetupRequiredError: credentiale lipsa, acces neaprobat inca, sau
                locatie/cont inexistente.
            ProviderError: raspuns neasteptat de la API.

        Cand contul nu e configurat, recenziile lipsesc dar numele si
        categoriile se intorc oricum: un semnal partial e mai util decat o
        eroare, si ``review_count=0`` spune singur ca n-am avut recenzii.
        """
        account_id, resolved_location = split_location_ref(
            self._location_id or location_id, fallback_account_id=self._account_id
        )
        name, categories = self._business_info(resolved_location)

        if not account_id:
            logger.warning(
                "contul Business Profile nu e configurat - intorc semnale fara recenzii "
                "pentru locatia %s",
                resolved_location,
            )
            return {
                "name": name,
                "categories": categories,
                "review_count": 0,
                "avg_rating": 0.0,
                "reviews": [],
            }

        raw_reviews, average, total = self._reviews(account_id, resolved_location)
        reviews: list[dict[str, object]] = []
        ratings: list[float] = []
        for raw in raw_reviews:
            rating = _STAR_RATINGS.get(str(raw.get("starRating", "")).upper())
            if rating is not None:
                ratings.append(rating)
            text = str(raw.get("comment", "")).strip()
            if not text:
                # O recenzie fara text are nota, dar nimic de analizat. Intra in
                # medie prin `ratings`, nu in lista de sentimente.
                continue
            score, label = score_sentiment(text)
            reviews.append({"text": text, "score": score, "label": label})

        if not average and ratings:
            average = sum(ratings) / len(ratings)
        return {
            "name": name,
            "categories": categories,
            "review_count": total or len(raw_reviews),
            "avg_rating": round(average, 1),
            "reviews": reviews,
        }
