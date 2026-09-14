"""Client live pentru Google Ads API (REST, fara SDK gRPC).

Acelasi pattern ca :class:`~ppc_agent.copywriter.llm.LiveLLMClient`: ``httpx``
simplu, ``transport`` injectabil pentru teste deterministe
(``httpx.MockTransport``, fara retea reala). Nu foloseste clientul oficial
``google-ads`` (gRPC/protobuf) — dependinta grea, greu de instalat pe Windows,
inconsistenta cu restul codebase-ului (100% httpx).
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import GoogleAdsProvider

_API_VERSION = "v25"  # Google Ads API - bump cand Google depreciaza versiunea.
_BASE_URL = f"https://googleads.googleapis.com/{_API_VERSION}"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 50

_PERFORMANCE_QUERY = (
    "SELECT campaign.id, campaign.name, metrics.clicks, metrics.conversions, "
    "metrics.cost_micros, metrics.conversions_value FROM campaign "
    "WHERE segments.date DURING LAST_30_DAYS"
)

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

    def _search(self, customer_id: str, query: str) -> list[dict[str, Any]]:
        if not self._developer_token:
            raise SetupRequiredError(
                "PPC_GOOGLE_ADS_DEVELOPER_TOKEN lipseste - completeaza-l in .env."
            )
        if not customer_id:
            raise SetupRequiredError(
                "customer_id lipseste - seteaza PPC_GOOGLE_ADS_CUSTOMER_ID in .env."
            )
        access_token = self._access_token()
        headers = {
            "Content-Type": "application/json",
            "developer-token": self._developer_token,
            "Authorization": f"Bearer {access_token}",
        }
        if self._login_customer_id:
            headers["login-customer-id"] = self._login_customer_id

        url = f"{_BASE_URL}/customers/{customer_id}/googleAds:search"
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(_MAX_PAGES):
            body: dict[str, Any] = {"query": query}
            if page_token:
                body["pageToken"] = page_token
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
                    f"Google Ads API a raspuns cu eroarea {response.status_code}: "
                    f"{response.text[:200]}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError(f"raspuns Google Ads API invalid (nu e JSON): {exc}") from exc

            results.extend(data.get("results", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return results

    def campaign_performance(self, customer_id: str) -> pd.DataFrame:
        """Performanta pe campanii (30 de zile), citita din Google Ads API."""
        rows = self._search(customer_id, _PERFORMANCE_QUERY)
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                campaign = row["campaign"]
                metrics = row["metrics"]
                out.append(
                    {
                        "arm_id": str(campaign["id"]),
                        "name": str(campaign["name"]),
                        "clicks": int(metrics.get("clicks", 0)),
                        "conversions": round(float(metrics.get("conversions", 0))),
                        "cost": float(metrics.get("costMicros", 0)) / 1_000_000,
                        "revenue": float(metrics.get("conversionsValue", 0)),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"rand Google Ads API cu forma neasteptata: {exc}"
                ) from exc
        columns = ["arm_id", "name", "clicks", "conversions", "cost", "revenue"]
        return pd.DataFrame(out, columns=columns)

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
