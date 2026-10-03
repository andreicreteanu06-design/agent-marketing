"""Client live pentru OpenAI Ads (reclamele din ChatGPT), REST simplu.

Scris dupa documentatia publica (developers.openai.com/ads), cu ``httpx`` simplu si
``transport`` injectabil, ca restul providerilor. Accesul la API il dau partenerii
aprobati de OpenAI: o cheie Ads API e legata de UN cont de reclame, deci contul nu se
alege din parametri - vine din cheie.

Bugetul sta pe campanie (``budget.daily_spend_limit_micros`` sau, la bugetele pe viata,
``lifetime_spend_limit_micros``), deci bratele planului de buget sunt campaniile.
Cheltuiala si click-urile vin din ``/ad_account/insights``, conversiile si vanzarile
atribuite din ``/conversions/insights``.

Neverificat pe un cont real (nu exista inca acces de partener): unitatea campului
``spend`` din insights nu e precizata in documentatie - aici e citita in moneda
contului, ca ``cpc``/``cpm`` de langa ea. Verifica pe primul cont: o cheltuiala de un
milion de ori prea mare ar face ROAS-ul aproape 0 (Kelly ar taia, nu ar creste).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError

_BASE_URL = "https://api.ads.openai.com/v1"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 20
_WINDOW_DAYS = 30
_MICROS = Decimal("1000000")
_CENT = Decimal("0.01")
#: Ca la Google si TikTok: un singur touchpoint per conversie, plafonat.
_MAX_PATHS_PER_ARM = 500

#: Parametrii de URL: listele se repeta (``time_ranges=...&time_ranges=...``).
_Params = list[tuple[str, str | int | float | bool | None]]

_COLUMNS = [
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


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _date_range(days: int) -> str:
    end = datetime.now(tz=UTC).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return json.dumps(
        {
            "type": "date_range",
            "since": start.isoformat(),
            "until": end.isoformat(),
            "timezone": "UTC",
        }
    )


class LiveChatGptAdsProvider:
    """Campaniile OpenAI Ads ale contului legat de cheie: performanta pe 30 de zile."""

    def __init__(
        self,
        *,
        api_key: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def request(
        self,
        method: str,
        path: str,
        *,
        params: _Params | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Un apel autentificat catre ``api.ads.openai.com/v1{path}``; corpul JSON."""
        if not self._api_key:
            raise SetupRequiredError(
                "cheia OpenAI Ads lipseste - conecteaz-o din contul clientului "
                "(chatgpt_ads_api_key) sau PPC_CHATGPT_ADS_API_KEY in .env."
            )
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.request(
                    method,
                    f"{_BASE_URL}{path}",
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"OpenAI Ads API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"OpenAI Ads API nu a raspuns in {self._timeout:.0f}s."
            ) from exc
        try:
            data: object = response.json()
        except ValueError:
            data = None
        if response.status_code in (401, 403):
            raise SetupRequiredError(
                f"OpenAI Ads a refuzat cheia ({response.status_code}): {_message(data)}. "
                "Verifica cheia si accesul de partener al contului."
            )
        if response.is_error:
            raise ProviderError(
                f"OpenAI Ads API a raspuns cu eroarea {response.status_code}: {_message(data)}"
            )
        if not isinstance(data, dict):
            raise ProviderError(f"raspuns OpenAI Ads invalid (HTTP {response.status_code})")
        return data

    def _list(self, path: str, params: _Params) -> list[dict[str, Any]]:
        """Toate paginile unei liste (cursor ``after`` = ``last_id``, cat timp ``has_more``)."""
        rows: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(_MAX_PAGES):
            page = self.request(
                "GET", path, params=[*params, *((("after", after),) if after else ())]
            )
            rows.extend(item for item in page.get("data", []) if isinstance(item, dict))
            after = page.get("last_id")
            if not page.get("has_more") or not after:
                break
        return rows

    def campaign_performance(self, account_id: str = "") -> pd.DataFrame:
        """Campaniile (30 de zile): click-uri, cost, conversii, vanzari atribuite, buget.

        ``account_id`` e ignorat: cheia e legata de un singur cont de reclame.
        """
        campaigns = self._list("/campaigns", [("limit", 500)])
        window = _date_range(_WINDOW_DAYS)
        delivery = {
            str(row.get("campaign_id")): row
            for row in self._list(
                "/ad_account/insights",
                [
                    ("aggregation_level", "campaign"),
                    ("time_granularity", "none"),
                    ("time_ranges", window),
                    ("limit", 2000),
                ],
            )
        }
        conversions = {
            str(row.get("entity_id")): row
            for row in self.request(
                "POST",
                "/conversions/insights",
                body={
                    "aggregation_level": "campaign",
                    "time_ranges": [window],
                    "time_granularity": "none",
                },
            ).get("data", [])
            if isinstance(row, dict)
        }
        out: list[dict[str, Any]] = []
        for campaign in campaigns:
            try:
                arm_id = str(campaign["id"])
                budget = campaign.get("budget") or {}
                daily = budget.get("daily_spend_limit_micros")
                spent = delivery.get(arm_id, {})
                converted = conversions.get(arm_id, {})
                out.append(
                    {
                        "arm_id": arm_id,
                        "name": str(campaign.get("name", arm_id)),
                        "clicks": int(_decimal(spent.get("clicks"))),
                        "conversions": round(float(_decimal(converted.get("conversions")))),
                        "cost": float(_decimal(spent.get("spend"))),
                        "revenue": float(_decimal(converted.get("order_created_attributed_sales"))),
                        "active": campaign.get("status") == "active",
                        "daily_budget": (
                            (_decimal(daily) / _MICROS).quantize(_CENT)
                            if daily is not None
                            else None
                        ),
                        "budget_locked": "" if daily is not None else "buget pe viata, nu zilnic",
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(f"campanie OpenAI Ads cu forma neasteptata: {exc}") from exc
        return pd.DataFrame(out, columns=_COLUMNS)

    def conversion_paths(self, account_id: str = "") -> list[list[str]]:
        """Parcursuri single-touch, ca la Google si TikTok (fara semnal multi-touch real)."""
        paths: list[list[str]] = []
        for record in self.campaign_performance(account_id).to_dict(orient="records"):
            clicks, conversions = int(record["clicks"]), int(record["conversions"])
            if clicks > _MAX_PATHS_PER_ARM:
                conversions = round(conversions * _MAX_PATHS_PER_ARM / clicks)
                clicks = _MAX_PATHS_PER_ARM
            name = str(record["name"])
            paths += [[name, "conversion"]] * conversions
            paths += [[name, "null"]] * max(0, clicks - conversions)
        return paths


class LiveChatGptAdsMutations:
    """Bugetul zilnic si pauza unei campanii OpenAI Ads. ``async`` ca la Meta."""

    def __init__(self, reader: LiveChatGptAdsProvider) -> None:
        self._reader = reader

    @staticmethod
    def _path(campaign_id: str) -> str:
        if not campaign_id.replace("_", "").isalnum():
            raise ProviderError(f"id de campanie OpenAI Ads invalid: {campaign_id!r}")
        return f"/campaigns/{campaign_id}"

    async def account_currency(self) -> str:
        """Moneda contului: plafonul de siguranta e in lei."""
        return str(self._reader.request("GET", "/ad_account").get("currency", ""))

    async def current_daily_budget(self, campaign_id: str) -> Decimal | None:
        """Bugetul zilnic de acum; ``None`` la un buget pe viata."""
        budget = self._reader.request("GET", self._path(campaign_id)).get("budget") or {}
        daily = budget.get("daily_spend_limit_micros")
        return (_decimal(daily) / _MICROS).quantize(_CENT) if daily is not None else None

    async def update_campaign_budget(self, campaign_id: str, new_daily_budget: Decimal) -> None:
        """Doar bugetele zilnice: OpenAI nu intoarce o campanie de la zilnic la pe viata,
        iar unul pe viata nu se muta in pasi zilnici."""
        if await self.current_daily_budget(campaign_id) is None:
            raise ProviderError(
                f"campania OpenAI Ads {campaign_id} are buget pe viata - schimba-l manual"
            )
        micros = int((new_daily_budget * _MICROS).to_integral_value())
        self._reader.request(
            "POST",
            self._path(campaign_id),
            body={"budget": {"daily_spend_limit_micros": micros}},
        )

    async def pause_campaign(self, campaign_id: str) -> None:
        self._reader.request("POST", f"{self._path(campaign_id)}/pause")


def _message(data: object) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message", ""))[:200]
        if isinstance(error, str):
            return error[:200]
    return ""
