"""Client live pentru TikTok Business API (Reporting, REST simplu).

Acelasi pattern ca :mod:`ppc_agent.providers.live.google_ads`/``meta`` —
``httpx`` simplu, ``transport`` injectabil pentru teste deterministe. Fara
SDK-ul oficial ``tiktok-business-api-sdk`` (dependinta suplimentara,
inconsistenta cu restul codebase-ului).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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
_CENT = Decimal("0.01")
#: Doar bugetele zilnice se muta in pasi; unul pe viata sau pe campanie, nu.
_DAILY_BUDGET = "BUDGET_MODE_DAY"

logger = logging.getLogger("ppc_agent.providers.live.tiktok")

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


def _number(value: object) -> Decimal:
    """Un camp numeric din raportul TikTok ("12.5", "-" fara date) ca ``Decimal``."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


class LiveTikTokAdsProvider(TikTokAdsProvider):
    """Client real pentru grupurile de anunturi TikTok: raportare, bugete, evenimente.

    Venitul vine dintr-un raport separat (comenzile pixelului: ``complete_payment`` x
    ``value_per_complete_payment``). Daca TikTok il refuza (pixel fara evenimentul de
    cumparare, metrica indisponibila pe cont), venitul ramane 0, iar planul de buget
    valoreaza vanzarile la cosul mediu (``decision.pipeline.value_unreported_conversions``)
    - nu cade tot planul pentru o metrica.
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

    def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Un apel autentificat (``Access-Token``) catre ``open_api/v1.3{path}``; ``data``.

        TikTok raspunde 200 si la erori, cu ``code`` diferit de 0: autentificarea devine
        :class:`SetupRequiredError`, restul ``ProviderError``.
        """
        if not self._access_token:
            raise SetupRequiredError(
                "PPC_TIKTOK_ACCESS_TOKEN lipseste - completeaza-l in .env pentru modul live."
            )
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.request(
                    method,
                    f"{_BASE_URL}{path}",
                    params=params,
                    json=body,
                    headers={"Access-Token": self._access_token},
                )
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"TikTok Business API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"TikTok Business API nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns TikTok Business API invalid (nu e JSON): {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("raspuns TikTok Business API invalid (nu e un obiect JSON)")

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
        payload = data.get("data")
        return payload if isinstance(payload, dict) else {}

    def _pages(self, path: str, params: dict[str, str | int]) -> list[dict[str, Any]]:
        """Toate paginile unei liste (``page``/``page_info.total_page``)."""
        rows: list[dict[str, Any]] = []
        page = 1
        for _ in range(_MAX_PAGES):
            payload = self.call(
                "GET", path, params={**params, "page": page, "page_size": _PAGE_SIZE}
            )
            rows.extend(payload.get("list", []))
            page_info = payload.get("page_info") or {}
            total_page = int(page_info.get("total_page", 1) or 1)
            if page >= total_page:
                break
            page += 1
        return rows

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
        return self._pages(
            "/report/integrated/get/",
            {
                "advertiser_id": advertiser_id,
                "report_type": "BASIC",
                "data_level": data_level,
                "dimensions": json.dumps(dimensions),
                "metrics": json.dumps(metrics),
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    def adgroups(
        self, advertiser_id: str, adgroup_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Grupurile de anunturi cu bugetul si starea lor (``/adgroup/get/``)."""
        params: dict[str, str | int] = {
            "advertiser_id": advertiser_id,
            "fields": json.dumps(["adgroup_id", "budget", "budget_mode", "operation_status"]),
        }
        if adgroup_ids is not None:
            params["filtering"] = json.dumps({"adgroup_ids": adgroup_ids})
        return self._pages("/adgroup/get/", params)

    def _purchase_values(
        self, advertiser_id: str, start_date: str, end_date: str
    ) -> dict[str, Decimal]:
        """Valoarea comenzilor din pixel, pe grup de anunturi; ``{}`` cand TikTok o refuza."""
        try:
            rows = self._report(
                advertiser_id,
                data_level="AUCTION_ADGROUP",
                dimensions=["adgroup_id"],
                metrics=["complete_payment", "value_per_complete_payment"],
                start_date=start_date,
                end_date=end_date,
            )
        except ProviderError as exc:
            logger.warning("TikTok: valoarea comenzilor indisponibila (%s) - cos mediu", exc)
            return {}
        values: dict[str, Decimal] = {}
        for row in rows:
            metrics = row.get("metrics", {})
            adgroup_id = str(row.get("dimensions", {}).get("adgroup_id", ""))
            value = _number(metrics.get("complete_payment")) * _number(
                metrics.get("value_per_complete_payment")
            )
            if adgroup_id and value > 0:
                values[adgroup_id] = value.quantize(_CENT)
        return values

    def _budgets(self, advertiser_id: str) -> dict[str, dict[str, Any]] | None:
        """Bugetul si starea fiecarui grup; ``None`` cand nu se pot citi."""
        try:
            return {str(row["adgroup_id"]): row for row in self.adgroups(advertiser_id)}
        except (ProviderError, KeyError, TypeError) as exc:
            logger.warning("TikTok: bugetele grupurilor nu s-au putut citi (%s)", exc)
            return None

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
        values = self._purchase_values(advertiser_id, start_date, end_date)
        budgets = self._budgets(advertiser_id)
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                dims = row.get("dimensions", {})
                metrics = row.get("metrics", {})
                arm_id = str(dims["adgroup_id"])
                adgroup = (budgets or {}).get(arm_id, {})
                daily = adgroup.get("budget_mode") == _DAILY_BUDGET
                if budgets is None:
                    locked = "bugetul de acum nu s-a putut citi"
                elif not daily:
                    locked = "buget pe campanie sau pe viata, nu zilnic pe grup"
                else:
                    locked = ""
                out.append(
                    {
                        "arm_id": arm_id,
                        "name": str(metrics.get("adgroup_name", arm_id)),
                        "clicks": int(float(metrics.get("clicks", 0))),
                        "conversions": round(float(metrics.get("conversion", 0))),
                        "cost": float(metrics.get("spend", 0)),
                        "revenue": float(values.get(arm_id, 0)),
                        # Un grup sters nu mai apare in /adgroup/get/.
                        "active": budgets is None
                        or adgroup.get("operation_status", "") == "ENABLE",
                        "daily_budget": (
                            _number(adgroup.get("budget")).quantize(_CENT) if daily else None
                        ),
                        "budget_locked": locked,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"rand TikTok Business API cu forma neasteptata: {exc}"
                ) from exc
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

    def track_event(self, payload: dict[str, Any]) -> None:
        """TikTok Events API (``/event/track/``): conversiile de pe server, ca la Meta CAPI."""
        self.call("POST", "/event/track/", body=payload)

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


class LiveTikTokMutations:
    """Schimbarile aplicate in contul TikTok ``advertiser_id``: bugetul si pauza unui grup
    de anunturi, pauza unui anunt. ``async`` ca la Meta (vezi ``LiveGoogleAdsMutations``)."""

    def __init__(self, reader: LiveTikTokAdsProvider, advertiser_id: str) -> None:
        self._reader = reader
        self._advertiser_id = advertiser_id

    async def account_currency(self) -> str:
        """Moneda contului: plafonul de siguranta e in lei."""
        payload = self._reader.call(
            "GET",
            "/advertiser/info/",
            params={
                "advertiser_ids": json.dumps([self._advertiser_id]),
                "fields": json.dumps(["currency"]),
            },
        )
        accounts = payload.get("list") or []
        if not accounts:
            raise ProviderError("TikTok nu a intors moneda contului")
        return str(accounts[0].get("currency", ""))

    def _adgroup(self, adgroup_id: str) -> dict[str, Any] | None:
        found = self._reader.adgroups(self._advertiser_id, [adgroup_id])
        return found[0] if found else None

    async def current_daily_budget(self, adgroup_id: str) -> Decimal | None:
        """Bugetul zilnic de acum al grupului; ``None`` daca nu are unul zilnic al lui."""
        adgroup = self._adgroup(adgroup_id)
        if adgroup is None or adgroup.get("budget_mode") != _DAILY_BUDGET:
            return None
        return _number(adgroup.get("budget")).quantize(_CENT)

    async def update_adgroup_budget(self, adgroup_id: str, new_daily_budget: Decimal) -> None:
        if await self.current_daily_budget(adgroup_id) is None:
            raise ProviderError(
                f"grupul TikTok {adgroup_id} nu are buget zilnic propriu (e pe campanie "
                "sau pe viata) - schimba-l manual"
            )
        self._reader.call(
            "POST",
            "/adgroup/update/",
            body={
                "advertiser_id": self._advertiser_id,
                "adgroup_id": adgroup_id,
                "budget": float(new_daily_budget),
            },
        )

    async def pause_adgroup(self, adgroup_id: str) -> None:
        self._reader.call(
            "POST",
            "/adgroup/status/update/",
            body={
                "advertiser_id": self._advertiser_id,
                "adgroup_ids": [adgroup_id],
                "operation_status": "DISABLE",
            },
        )

    async def pause_ad(self, ad_id: str) -> None:
        self._reader.call(
            "POST",
            "/ad/status/update/",
            body={
                "advertiser_id": self._advertiser_id,
                "ad_ids": [ad_id],
                "operation_status": "DISABLE",
            },
        )
