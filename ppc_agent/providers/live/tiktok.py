"""Client live pentru TikTok Business API (Reporting, REST simplu).

Acelasi pattern ca :mod:`ppc_agent.providers.live.google_ads`/``meta`` —
``httpx`` simplu, ``transport`` injectabil pentru teste deterministe. Fara
SDK-ul oficial ``tiktok-business-api-sdk`` (dependinta suplimentara,
inconsistenta cu restul codebase-ului).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import TikTokAdsProvider

_API_VERSION = "v1.3"
_BASE_URL = f"https://business-api.tiktok.com/open_api/{_API_VERSION}"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 20
_PAGE_SIZE = 200
_REPORT_WINDOW_DAYS = 30

# Cuvinte-cheie euristice pentru a distinge o eroare de autentificare de una de
# continut al cererii (nu am putut confirma codurile numerice exacte ale
# TikTok Business API la momentul scrierii - vezi nota din plan).
_AUTH_HINT_WORDS = ("token", "auth", "access")

# Vezi google_ads.py::_single_touch_paths - acelasi fallback (raportarea
# TikTok nu expune parcursuri multi-touch), duplicat deliberat aici.
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


def _last_n_days(days: int) -> tuple[str, str]:
    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


class LiveTikTokAdsProvider(TikTokAdsProvider):
    """Client real pentru performanta grupurilor de anunturi TikTok (citire).

    Gap onest, mai serios decat la Google/Meta: raportul de baza (``metrics``
    de mai jos) nu include un camp de *valoare/venit* per conversie confirmat -
    depinde de evenimentul de pixel/API configurat de agentie pe cont, iar
    documentatia publica accesibila la scriere nu a confirmat numele exact al
    campului. ``revenue`` ramane ``0.0`` pana la verificare manuala cu un token
    real (vezi ``campaign_performance``).
    """

    def __init__(
        self,
        *,
        access_token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._access_token = access_token
        self._timeout = timeout
        self._transport = transport

    @property
    def access_token_configured(self) -> bool:
        """Adevarat daca ``access_token`` a fost setat (fara sa il expuna)."""
        return bool(self._access_token)

    def _report(
        self,
        advertiser_id: str,
        *,
        data_level: str,
        dimensions: list[str],
        metrics: list[str],
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        if not self._access_token:
            raise SetupRequiredError(
                "PPC_TIKTOK_ACCESS_TOKEN lipseste - completeaza-l in .env pentru modul live."
            )
        if not advertiser_id:
            raise SetupRequiredError(
                "advertiser_id lipseste - seteaza PPC_TIKTOK_ADVERTISER_ID in .env."
            )

        headers = {"Access-Token": self._access_token}
        url = f"{_BASE_URL}/report/integrated/get/"
        rows: list[dict[str, Any]] = []
        page = 1
        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {
                "advertiser_id": advertiser_id,
                "report_type": "BASIC",
                "data_level": data_level,
                "dimensions": json.dumps(dimensions),
                "metrics": json.dumps(metrics),
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "page_size": _PAGE_SIZE,
            }
            try:
                with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                    response = client.get(url, params=params, headers=headers)
            except httpx.ConnectError as exc:
                raise SetupRequiredError(
                    f"TikTok Business API nu raspunde la {_BASE_URL}."
                ) from exc
            except httpx.TimeoutException as exc:
                raise SetupRequiredError(
                    f"TikTok Business API nu a raspuns in {self._timeout:.0f}s."
                ) from exc

            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError(
                    f"raspuns TikTok Business API invalid (nu e JSON): {exc}"
                ) from exc

            code = data.get("code")
            if response.status_code >= 400 or code not in (0, None):
                message = str(data.get("message", response.text[:200]))
                looks_like_auth = response.status_code in (401, 403) or any(
                    word in message.lower() for word in _AUTH_HINT_WORDS
                )
                if looks_like_auth:
                    raise SetupRequiredError(
                        f"TikTok Business API a refuzat cererea: {message}. "
                        "PPC_TIKTOK_ACCESS_TOKEN e probabil expirat/invalid - regenereaza-l."
                    )
                raise ProviderError(f"TikTok Business API a raspuns cu eroarea: {message}")

            payload = data.get("data") or {}
            rows.extend(payload.get("list", []))
            page_info = payload.get("page_info") or {}
            total_page = int(page_info.get("total_page", 1) or 1)
            if page >= total_page:
                break
            page += 1
        return rows

    def campaign_performance(self, advertiser_id: str) -> pd.DataFrame:
        """Performanta pe grupuri de anunturi (30 de zile), pentru Modulul 2 (bandit)."""
        start_date, end_date = _last_n_days(_REPORT_WINDOW_DAYS)
        rows = self._report(
            advertiser_id,
            data_level="AUCTION_ADGROUP",
            dimensions=["adgroup_id"],
            metrics=["adgroup_name", "clicks", "conversion", "spend"],
            start_date=start_date,
            end_date=end_date,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                dims = row.get("dimensions", {})
                metrics = row.get("metrics", {})
                arm_id = str(dims["adgroup_id"])
                out.append(
                    {
                        "arm_id": arm_id,
                        "name": str(metrics.get("adgroup_name", arm_id)),
                        "clicks": int(float(metrics.get("clicks", 0))),
                        "conversions": round(float(metrics.get("conversion", 0))),
                        "cost": float(metrics.get("spend", 0)),
                        # Gap documentat in docstring-ul clasei - vezi mai sus.
                        "revenue": 0.0,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"rand TikTok Business API cu forma neasteptata: {exc}"
                ) from exc
        columns = ["arm_id", "name", "clicks", "conversions", "cost", "revenue"]
        return pd.DataFrame(out, columns=columns)

    def conversion_paths(self, advertiser_id: str) -> list[list[str]]:
        """Parcursuri single-touch sintetizate din performanta pe grupuri de anunturi.

        Gap onest: raportarea TikTok nu expune parcursuri multi-touch in
        aceasta forma - vezi ``_MAX_PATHS_PER_ARM`` mai sus.
        """
        frame = self.campaign_performance(advertiser_id)
        paths: list[list[str]] = []
        for record in frame.to_dict(orient="records"):
            paths.extend(
                _single_touch_paths(
                    str(record["name"]), int(record["clicks"]), int(record["conversions"])
                )
            )
        return paths
