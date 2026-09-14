"""Client live pentru Meta Marketing API (Graph API, REST simplu).

Acelasi pattern ca :mod:`ppc_agent.providers.live.google_ads` — ``httpx``
simplu, ``transport`` injectabil pentru teste deterministe. Fara SDK-ul oficial
``facebook-business`` (dependinta grea, inconsistenta cu restul codebase-ului).
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.base import MetaMarketingProvider

_API_VERSION = "v25.0"  # Graph API - Meta reviseaza de ~2x/an.
_BASE_URL = f"https://graph.facebook.com/{_API_VERSION}"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 20

# error.code 190 = OAuthException (token expirat/revocat/invalid) - documentat
# de Meta ca eroare de autentificare, nu de continut al cererii.
_AUTH_ERROR_CODES = frozenset({190})
_LEARNING_STATUSES = frozenset({"LEARNING", "LEARNING_LIMITED"})

# Tipurile de "actions" numarate ca si conversii/venit - proxy, la fel ca
# default_lead_value deja existent in proiect (depinde de evenimentele de
# pixel/CAPI configurate de agentie pe contul respectiv).
_CONVERSION_ACTION_TYPES = frozenset(
    {
        "purchase",
        "omni_purchase",
        "lead",
        "offsite_conversion.fb_pixel_lead",
        "onsite_conversion.lead_grouped",
    }
)

# Vezi google_ads.py::_single_touch_paths - acelasi fallback (Meta Insights nu
# expune parcursuri multi-touch simplu), duplicat aici deliberat ca fiecare
# Live*Provider sa ramana auditabil de sine statator.
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


def _summarize_targeting(targeting: dict[str, Any]) -> str:
    """Rezuma ``targeting`` intr-un sir de tokene.

    Singurul loc unde ``audience_def`` conteaza efectiv e clustering-ul Jaccard
    din :func:`ppc_agent.alignment.meta_liquidity._audience_tokens` — nu
    trebuie sa reproduca UI-ul Meta Ads Manager, doar sa dea tokene descriptive.
    """
    tokens: list[str] = []
    age_min, age_max = targeting.get("age_min"), targeting.get("age_max")
    if age_min:
        tokens.append(str(age_min))
    if age_max:
        tokens.append(str(age_max))
    geo = targeting.get("geo_locations") or {}
    tokens.extend(str(c) for c in geo.get("countries", []))
    tokens.extend(str(r.get("name", "")) for r in geo.get("regions", []))
    for spec in targeting.get("flexible_spec", []) or []:
        tokens.extend(str(i.get("name", "")) for i in spec.get("interests", []))
        tokens.extend(str(b.get("name", "")) for b in spec.get("behaviors", []))
    if targeting.get("custom_audiences"):
        tokens.append("custom_audience")
    cleaned = [t.lower() for t in tokens if t]
    return " ".join(cleaned) if cleaned else "audienta nesegmentata"


class LiveMetaMarketingProvider(MetaMarketingProvider):
    """Client real pentru seturile de reclame Meta (citire, Graph API)."""

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

    def _headers(self) -> dict[str, str]:
        if not self._access_token:
            raise SetupRequiredError(
                "PPC_META_ACCESS_TOKEN lipseste - completeaza-l in .env pentru modul live."
            )
        return {"Authorization": f"Bearer {self._access_token}"}

    def _request(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        headers = self._headers()
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.get(url, params=params, headers=headers)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Meta Graph API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Meta Graph API nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns Meta Graph API invalid (nu e JSON): {exc}") from exc

        error = data.get("error")
        if response.status_code >= 400 or error is not None:
            error = error or {}
            code = error.get("code")
            message = error.get("message") or response.text[:200]
            if response.status_code in (401, 403) or code in _AUTH_ERROR_CODES:
                raise SetupRequiredError(
                    f"Meta Graph API a refuzat autentificarea: {message}. "
                    "PPC_META_ACCESS_TOKEN e probabil expirat/revocat - regenereaza-l."
                )
            raise ProviderError(f"Meta Graph API a raspuns cu eroarea: {message}")
        return data

    def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{_BASE_URL}/{path}"
        current_params: dict[str, Any] | None = params
        items: list[dict[str, Any]] = []
        for _ in range(_MAX_PAGES):
            data = self._request(url, current_params)
            items.extend(data.get("data", []))
            next_url = (data.get("paging") or {}).get("next")
            if not next_url:
                break
            url = next_url
            current_params = None  # deja incluse in URL-ul de pagina urmatoare
        return items

    def ad_sets(self, ad_account_id: str) -> pd.DataFrame:
        """Seturile de reclame + performanta ultimelor 7 zile (pentru lichiditate)."""
        adsets = self._paginate(
            f"{ad_account_id}/adsets",
            {"fields": "id,name,targeting,learning_stage_info", "limit": 200},
        )
        insights = self._paginate(
            f"{ad_account_id}/insights",
            {
                "level": "adset",
                "date_preset": "last_7d",
                "fields": "adset_id,spend,actions",
                "limit": 200,
            },
        )
        insight_by_id = {str(row["adset_id"]): row for row in insights if "adset_id" in row}

        rows: list[dict[str, Any]] = []
        for adset in adsets:
            adset_id = str(adset.get("id", ""))
            insight = insight_by_id.get(adset_id, {})
            actions = insight.get("actions", []) or []
            weekly_conversions = sum(
                float(a["value"])
                for a in actions
                if a.get("action_type") in _CONVERSION_ACTION_TYPES
            )
            learning_status = str((adset.get("learning_stage_info") or {}).get("status", ""))
            rows.append(
                {
                    "ad_set_id": adset_id,
                    "name": str(adset.get("name", "")),
                    "audience_def": _summarize_targeting(adset.get("targeting") or {}),
                    "weekly_conversions": weekly_conversions,
                    "weekly_spend": float(insight.get("spend", 0.0)),
                    "learning_phase": learning_status in _LEARNING_STATUSES,
                }
            )
        columns = [
            "ad_set_id",
            "name",
            "audience_def",
            "weekly_conversions",
            "weekly_spend",
            "learning_phase",
        ]
        return pd.DataFrame(rows, columns=columns)

    def campaign_performance(self, ad_account_id: str) -> pd.DataFrame:
        """Performanta pe seturi de reclame (30 de zile), pentru Modulul 2 (bandit)."""
        insights = self._paginate(
            f"{ad_account_id}/insights",
            {
                "level": "adset",
                "date_preset": "last_30d",
                "fields": "adset_id,adset_name,clicks,spend,actions,action_values",
                "limit": 200,
            },
        )
        out: list[dict[str, Any]] = []
        for row in insights:
            try:
                actions = row.get("actions", []) or []
                action_values = row.get("action_values", []) or []
                conversions = sum(
                    float(a["value"])
                    for a in actions
                    if a.get("action_type") in _CONVERSION_ACTION_TYPES
                )
                revenue = sum(
                    float(a["value"])
                    for a in action_values
                    if a.get("action_type") in _CONVERSION_ACTION_TYPES
                )
                out.append(
                    {
                        "arm_id": str(row["adset_id"]),
                        "name": str(row.get("adset_name", row["adset_id"])),
                        "clicks": int(row.get("clicks", 0)),
                        "conversions": round(conversions),
                        "cost": float(row.get("spend", 0.0)),
                        "revenue": revenue,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(f"rand Meta Insights cu forma neasteptata: {exc}") from exc
        columns = ["arm_id", "name", "clicks", "conversions", "cost", "revenue"]
        return pd.DataFrame(out, columns=columns)

    def conversion_paths(self, ad_account_id: str) -> list[list[str]]:
        """Parcursuri single-touch sintetizate din performanta pe seturi de reclame.

        Gap onest: Meta Insights nu expune parcursuri multi-touch in aceasta
        forma (ar cere produsul separat de Attribution) — vezi
        ``_MAX_PATHS_PER_ARM`` mai sus.
        """
        frame = self.campaign_performance(ad_account_id)
        paths: list[list[str]] = []
        for record in frame.to_dict(orient="records"):
            paths.extend(
                _single_touch_paths(
                    str(record["name"]), int(record["clicks"]), int(record["conversions"])
                )
            )
        return paths
