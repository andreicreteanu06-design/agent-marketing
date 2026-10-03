"""Client live pentru Google Ads API (REST, fara SDK gRPC).

Acelasi pattern ca :class:`~ppc_agent.copywriter.llm.LiveLLMClient`: ``httpx``
simplu, ``transport`` injectabil pentru teste deterministe
(``httpx.MockTransport``, fara retea reala). Nu foloseste clientul oficial
``google-ads`` (gRPC/protobuf) — dependinta grea, greu de instalat pe Windows,
inconsistenta cu restul codebase-ului (100% httpx).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import GoogleAdsProvider
from ppc_agent.providers.live.daily import DAILY_COLUMNS, daily_window

_API_VERSION = "v25"  # Google Ads API - bump cand Google depreciaza versiunea.
_BASE_URL = f"https://googleads.googleapis.com/{_API_VERSION}"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 50

_PERFORMANCE_QUERY = (
    "SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, "
    "campaign_budget.amount_micros, campaign_budget.explicitly_shared, "
    "campaign_budget.period, metrics.clicks, metrics.conversions, "
    "metrics.cost_micros, metrics.conversions_value FROM campaign "
    "WHERE segments.date DURING LAST_30_DAYS"
)
_MICROS = Decimal("1000000")
_CENT = Decimal("0.01")

#: Lista de cuvinte negative a platformei: una pe cont, atasata campaniilor de cautare.
NEGATIVE_LIST_NAME = "AC Media - cuvinte negative"
_MATCH_TYPES = {"exact": "EXACT", "phrase": "PHRASE", "broad": "BROAD"}
#: Numele de resurse intoarse de Google ajung inapoi in GAQL: doar forma asteptata.
_RESOURCE_NAME = re.compile(r"customers/\d+/[A-Za-z]+/[\d~]+")

# Parcursurile multi-touch (Multi-Channel Funnels) nu mai sunt expuse simplu de
# API-ul actual — fallback documentat: un singur touchpoint (numele campaniei)
# per conversie/non-conversie, plafonat ca sa nu explodeze atribuirea Markov pe
# conturi cu volum mare de click-uri. Pastreaza matematica Markov valida, dar
# fara semnal multi-touch real (gap onest, de imbunatatit cand exista un
# furnizor real de parcursuri, ex. Google Analytics 4 Data API).
_MAX_PATHS_PER_ARM = 500


def _single_touch_paths(name: str, clicks: int, conversions: int) -> list[list[str]]:
    total = clicks
    if total <= 0:
        return []
    if total > _MAX_PATHS_PER_ARM:
        conversions = round(conversions * _MAX_PATHS_PER_ARM / total)
        total = _MAX_PATHS_PER_ARM
    non_converting = max(0, total - conversions)
    return [[name, "conversion"] for _ in range(conversions)] + [
        [name, "null"] for _ in range(non_converting)
    ]


def _budget_lock(campaign: dict[str, Any], budget: dict[str, Any]) -> str:
    """De ce bugetul campaniei nu se muta din planul de noapte (gol = se poate muta)."""
    if budget.get("explicitlyShared"):
        return "buget partajat cu alte campanii"
    if budget.get("period") not in (None, "DAILY"):
        return "buget pe o perioada, nu zilnic"
    if campaign.get("primaryStatus") == "LEARNING":
        return "strategia de licitare e in invatare"
    return ""


class LiveGoogleAdsProvider(GoogleAdsProvider):
    """Client real pentru performanta campaniilor Google Ads (citire, REST)."""

    def __init__(
        self,
        *,
        developer_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        login_customer_id: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._developer_token = developer_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._login_customer_id = login_customer_id
        self._timeout = timeout
        self._transport = transport
        self._cached_access_token: str | None = None

    @property
    def developer_token(self) -> str:
        """Token-ul de dezvoltator configurat (gol daca nu e setat)."""
        return self._developer_token

    @property
    def login_customer_id(self) -> str:
        """ID-ul contului manager (MCC), daca e configurat."""
        return self._login_customer_id

    def _access_token(self) -> str:
        """Schimba ``refresh_token`` pe un access token OAuth2, cache in-instanta."""
        if self._cached_access_token is not None:
            return self._cached_access_token
        if not (self._client_id and self._client_secret and self._refresh_token):
            raise SetupRequiredError(
                "PPC_GOOGLE_ADS_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN lipsesc - "
                "completeaza-le in .env pentru modul live."
            )
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(_OAUTH_TOKEN_URL, data=payload)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(
                f"Nu se poate contacta {_OAUTH_TOKEN_URL} pentru refresh OAuth2."
            ) from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"OAuth2 Google nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        if response.status_code >= 400:
            raise SetupRequiredError(
                f"Google OAuth2 a refuzat refresh_token-ul ({response.status_code}): "
                f"{response.text[:200]}. Regenereaza-l (probabil revocat/expirat)."
            )
        try:
            token = response.json()["access_token"]
        except (KeyError, ValueError) as exc:
            raise ProviderError(f"raspuns OAuth2 Google neasteptat: {exc}") from exc

        self._cached_access_token = str(token)
        return self._cached_access_token

    def _post(self, customer_id: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Un ``POST`` autentificat catre ``customers/{customer_id}{path}``, cu erorile
        traduse: autentificarea -> :class:`SetupRequiredError`, restul -> ``ProviderError``."""
        if not self._developer_token:
            raise SetupRequiredError(
                "PPC_GOOGLE_ADS_DEVELOPER_TOKEN lipseste - completeaza-l in .env."
            )
        if not customer_id:
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
        url = f"{_BASE_URL}/customers/{customer_id}{path}"
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(url, headers=headers, json=body)
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
                "login_customer_id/permisiunile contului."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Google Ads API a raspuns cu eroarea {response.status_code}: {response.text[:200]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns Google Ads API invalid (nu e JSON): {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("raspuns Google Ads API invalid (nu e un obiect JSON)")
        return data

    def _search(self, customer_id: str, query: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(_MAX_PAGES):
            body: dict[str, Any] = {"query": query}
            if page_token:
                body["pageToken"] = page_token
            data = self._post(customer_id, "/googleAds:search", body)
            results.extend(data.get("results", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return results

    def search(self, customer_id: str, query: str) -> list[dict[str, Any]]:
        """Interogare GAQL, toate paginile - pentru :class:`LiveGoogleAdsMutations`."""
        return self._search(customer_id, query)

    def mutate(
        self, customer_id: str, service: str, operations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """``customers/{id}/{service}:mutate`` (ex. ``campaignBudgets``); rezultatele."""
        data = self._post(customer_id, f"/{service}:mutate", {"operations": operations})
        return list(data.get("results", []))

    def upload_click_conversion(self, customer_id: str, conversion: dict[str, Any]) -> None:
        """O conversie importata (``uploadClickConversions``).

        ``partialFailure`` e obligatoriu la acest serviciu: Google raspunde 200 si pune
        motivul refuzului (click negasit, actiune gresita) in ``partialFailureError``.

        Raises:
            ProviderError: Google a refuzat conversia.
        """
        data = self._post(
            customer_id,
            ":uploadClickConversions",
            {"conversions": [conversion], "partialFailure": True},
        )
        error = data.get("partialFailureError")
        if isinstance(error, dict) and error.get("message"):
            raise ProviderError(f"Google Ads a refuzat conversia: {str(error['message'])[:300]}")

    def campaign_performance(self, customer_id: str) -> pd.DataFrame:
        """Performanta pe campanii (30 de zile), citita din Google Ads API."""
        rows = self._search(customer_id, _PERFORMANCE_QUERY)
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                campaign = row["campaign"]
                metrics = row["metrics"]
                budget = row.get("campaignBudget") or {}
                micros = budget.get("amountMicros")
                out.append(
                    {
                        "arm_id": str(campaign["id"]),
                        "name": str(campaign["name"]),
                        "clicks": int(metrics.get("clicks", 0)),
                        "conversions": round(float(metrics.get("conversions", 0))),
                        "cost": float(metrics.get("costMicros", 0)) / 1_000_000,
                        "revenue": float(metrics.get("conversionsValue", 0)),
                        # Fara stare in raspuns, campania se considera activa.
                        "active": campaign.get("status", "ENABLED") == "ENABLED",
                        "daily_budget": (
                            (Decimal(str(micros)) / _MICROS).quantize(_CENT)
                            if micros is not None
                            else None
                        ),
                        "budget_locked": _budget_lock(campaign, budget),
                    }
                )
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                raise ProviderError(f"rand Google Ads API cu forma neasteptata: {exc}") from exc
        columns = [
            "arm_id",
            "name",
            "clicks",
            "conversions",
            "cost",
            "revenue",
            "active",
            "daily_budget",
            "budget_locked",
        ]
        return pd.DataFrame(out, columns=columns)

    def daily_campaign_performance(
        self, customer_id: str, *, days: int, end_date: date | None = None
    ) -> pd.DataFrame:
        """Performanta pe campanii, zi cu zi (GAQL cu ``segments.date``).

        Args:
            customer_id: Contul Google Ads.
            days: Cate zile, numarate inapoi de la ``end_date`` inclusiv.
            end_date: Ultima zi inclusa; implicit ieri.

        Returns:
            Aceleasi coloane ca :meth:`campaign_performance`, plus ``date``. Spre
            deosebire de agregatul pe 30 de zile, conversiile raman fractionare:
            o zi cu 0,4 conversii (atribuire data-driven) nu e o zi cu zero.

        Google omite zilele fara afisari - apelantul le completeaza cu zero.
        """
        start, end = daily_window(days, end_date)
        query = (
            "SELECT segments.date, campaign.id, campaign.name, metrics.clicks, "
            "metrics.conversions, metrics.cost_micros, metrics.conversions_value "
            f"FROM campaign WHERE segments.date BETWEEN '{start.isoformat()}' "
            f"AND '{end.isoformat()}'"
        )
        out: list[dict[str, Any]] = []
        for row in self._search(customer_id, query):
            try:
                campaign = row["campaign"]
                metrics = row["metrics"]
                out.append(
                    {
                        "date": date.fromisoformat(str(row["segments"]["date"])),
                        "arm_id": str(campaign["id"]),
                        "name": str(campaign["name"]),
                        "clicks": int(metrics.get("clicks", 0)),
                        "conversions": float(metrics.get("conversions", 0)),
                        "cost": float(metrics.get("costMicros", 0)) / 1_000_000,
                        "revenue": float(metrics.get("conversionsValue", 0)),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"rand zilnic Google Ads API cu forma neasteptata: {exc}"
                ) from exc
        return pd.DataFrame(out, columns=DAILY_COLUMNS)

    def conversion_paths(self, customer_id: str) -> list[list[str]]:
        """Parcursuri single-touch sintetizate din performanta pe campanii.

        Gap onest: Google Ads API nu mai expune parcursuri multi-touch simplu
        (vezi comentariul de la ``_MAX_PATHS_PER_ARM`` mai sus).
        """
        frame = self.campaign_performance(customer_id)
        paths: list[list[str]] = []
        for record in frame.to_dict(orient="records"):
            paths.extend(
                _single_touch_paths(
                    str(record["name"]), int(record["clicks"]), int(record["conversions"])
                )
            )
        return paths


class LiveGoogleAdsMutations:
    """Schimbarile aplicate in contul Google Ads ``customer_id``: buget, pauza, negative.

    Peste clientul de citire (aceeasi autentificare). Metodele sunt ``async`` ca la
    Meta, fiindca motorul de executie (``services/execution_engine.py``) asteapta
    corutine; apelurile HTTP raman sincrone.

    Cuvintele negative merg intr-o lista partajata a contului (``NEGATIVE_LIST_NAME``),
    atasata tuturor campaniilor de cautare active: un termen irelevant e irelevant
    pentru tot contul, nu doar pentru campania in care a aparut.
    """

    def __init__(self, reader: LiveGoogleAdsProvider, customer_id: str) -> None:
        self._reader = reader
        self._customer_id = customer_id.replace("-", "")

    def _campaign(self, campaign_id: str) -> int:
        if not campaign_id.isdigit():
            raise ProviderError(f"id de campanie Google Ads invalid: {campaign_id!r}")
        return int(campaign_id)

    def _budget_row(self, campaign_id: str) -> dict[str, Any] | None:
        rows = self._reader.search(
            self._customer_id,
            "SELECT campaign.id, campaign_budget.resource_name, campaign_budget.amount_micros, "
            "campaign_budget.explicitly_shared, campaign_budget.period FROM campaign "
            f"WHERE campaign.id = {self._campaign(campaign_id)}",
        )
        return rows[0].get("campaignBudget") if rows else None

    async def account_currency(self) -> str:
        """Moneda contului: plafonul de siguranta e in lei."""
        rows = self._reader.search(self._customer_id, "SELECT customer.currency_code FROM customer")
        if not rows:
            raise ProviderError("Google Ads nu a intors moneda contului")
        return str(rows[0].get("customer", {}).get("currencyCode", ""))

    async def current_daily_budget(self, campaign_id: str) -> Decimal | None:
        """Bugetul zilnic de acum al campaniei; ``None`` daca nu e unul zilnic, al ei."""
        budget = self._budget_row(campaign_id)
        if not budget or budget.get("explicitlyShared"):
            return None
        if budget.get("period") not in (None, "DAILY") or budget.get("amountMicros") is None:
            return None
        return (Decimal(str(budget["amountMicros"])) / _MICROS).quantize(_CENT)

    async def update_campaign_budget(self, campaign_id: str, new_daily_budget: Decimal) -> None:
        """Bugetul zilnic al campaniei. Un buget partajat nu se atinge: l-ar muta si pe
        al celorlalte campanii care il folosesc."""
        budget = self._budget_row(campaign_id)
        if not budget or not budget.get("resourceName"):
            raise ProviderError(f"campania Google Ads {campaign_id} nu are buget de modificat")
        if budget.get("explicitlyShared"):
            raise ProviderError(
                f"campania Google Ads {campaign_id} foloseste un buget partajat - "
                "schimba-l manual, ca sa vezi toate campaniile afectate"
            )
        micros = int((new_daily_budget * _MICROS).to_integral_value())
        self._reader.mutate(
            self._customer_id,
            "campaignBudgets",
            [
                {
                    "updateMask": "amountMicros",
                    "update": {"resourceName": budget["resourceName"], "amountMicros": str(micros)},
                }
            ],
        )

    async def pause_campaign(self, campaign_id: str) -> None:
        self._reader.mutate(
            self._customer_id,
            "campaigns",
            [
                {
                    "updateMask": "status",
                    "update": {
                        "resourceName": (
                            f"customers/{self._customer_id}/campaigns/{self._campaign(campaign_id)}"
                        ),
                        "status": "PAUSED",
                    },
                }
            ],
        )

    def _negative_list(self) -> str:
        rows = self._reader.search(
            self._customer_id,
            "SELECT shared_set.resource_name FROM shared_set "
            f"WHERE shared_set.name = '{NEGATIVE_LIST_NAME}' "
            "AND shared_set.type = 'NEGATIVE_KEYWORDS' AND shared_set.status = 'ENABLED'",
        )
        if rows:
            name = str(rows[0]["sharedSet"]["resourceName"])
        else:
            created = self._reader.mutate(
                self._customer_id,
                "sharedSets",
                [{"create": {"name": NEGATIVE_LIST_NAME, "type": "NEGATIVE_KEYWORDS"}}],
            )
            name = str(created[0]["resourceName"]) if created else ""
        if not _RESOURCE_NAME.fullmatch(name):
            raise ProviderError(f"lista de negative Google Ads cu nume neasteptat: {name!r}")
        return name

    async def add_negative_keyword(self, text: str, match_type: str) -> None:
        """Adauga ``text`` in lista de negative a contului si o ataseaza campaniilor de
        cautare active care nu o au. Idempotent: un termen deja in lista nu se dubleaza."""
        match = _MATCH_TYPES.get(match_type.strip().lower())
        if match is None:
            raise ProviderError(f"tip de potrivire necunoscut pentru negativ: {match_type!r}")
        keyword = text.strip()
        if not keyword:
            raise ProviderError("cuvant negativ gol")
        shared_set = self._negative_list()
        existing = {
            (
                str(row["sharedCriterion"]["keyword"]["text"]).lower(),
                str(row["sharedCriterion"]["keyword"]["matchType"]),
            )
            for row in self._reader.search(
                self._customer_id,
                "SELECT shared_criterion.keyword.text, shared_criterion.keyword.match_type "
                f"FROM shared_criterion WHERE shared_set.resource_name = '{shared_set}'",
            )
            if row.get("sharedCriterion", {}).get("keyword")
        }
        if (keyword.lower(), match) not in existing:
            self._reader.mutate(
                self._customer_id,
                "sharedCriteria",
                [
                    {
                        "create": {
                            "sharedSet": shared_set,
                            "keyword": {"text": keyword, "matchType": match},
                        }
                    }
                ],
            )
        campaigns = {
            str(row["campaign"]["resourceName"])
            for row in self._reader.search(
                self._customer_id,
                "SELECT campaign.resource_name FROM campaign WHERE "
                "campaign.advertising_channel_type = 'SEARCH' AND campaign.status = 'ENABLED'",
            )
        }
        attached = {
            str(row["campaignSharedSet"]["campaign"])
            for row in self._reader.search(
                self._customer_id,
                "SELECT campaign_shared_set.campaign FROM campaign_shared_set "
                f"WHERE shared_set.resource_name = '{shared_set}' "
                "AND campaign_shared_set.status = 'ENABLED'",
            )
        }
        missing = sorted(campaigns - attached)
        if missing:
            self._reader.mutate(
                self._customer_id,
                "campaignSharedSets",
                [
                    {"create": {"campaign": campaign, "sharedSet": shared_set}}
                    for campaign in missing
                ],
            )
