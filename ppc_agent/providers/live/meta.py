"""Client live pentru Meta Marketing API (Graph API, REST simplu).

Acelasi pattern ca :mod:`ppc_agent.providers.live.google_ads` — ``httpx``
simplu, ``transport`` injectabil pentru teste deterministe. Fara SDK-ul oficial
``facebook-business`` (dependinta grea, inconsistenta cu restul codebase-ului).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
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

# Meta primeste bugetele in unitatea MINIMA a monedei contului: pentru
# RON/EUR/USD aia e banul/centul (x100), dar pentru monedele de mai jos unitatea
# minima E moneda insasi (x1). Inmultirea oarba cu 100 ar trimite un buget de 100
# de ori mai mare - de-asta factorul e parametru, nu constanta.
#
# Lista acopera monedele uzuale fara subunitate. Sursa de adevar ramane Meta:
# fiecare moneda are un "offset" propriu (GET /{version}/currencies), iar HUF e
# cazul care arata de ce nu ne putem lua dupa ISO 4217 - acolo are 2 zecimale,
# la platformele de reclame e tratata fara. Daca un cont e intr-o moneda exotica,
# verifica offset-ul inainte, si seteaza PPC_META_CURRENCY corect.
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "HUF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "TWD",
        "UGX",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)
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


def minor_units_factor(currency: str) -> int:
    """Cu cat se inmulteste o suma ca sa ajunga in unitatea minima a monedei.

    Args:
        currency: Codul ISO al monedei contului de reclame (``RON``, ``EUR``...).

    Returns:
        ``1`` pentru monedele fara subunitate, ``100`` pentru restul.
    """
    return 1 if currency.strip().upper() in _ZERO_DECIMAL_CURRENCIES else 100


class LiveMetaMarketingProvider(MetaMarketingProvider):
    """Client real pentru seturile de reclame Meta: citire sincrona, scriere async.

    Citirea a ramas sincrona (``httpx.Client``) - asa o consuma Modulele 2 si 3.
    Mutatiile sunt ``async`` fiindca aprobarea mai multor propuneri deodata
    beneficiaza de concurenta, iar puntea catre stratul sincron se face intr-un
    singur loc (``services/execution_engine.py``), la fel ca la
    ``search_data/serp_tracker.py::check_rankings_sync``.
    """

    def __init__(
        self,
        *,
        access_token: str = "",
        currency: str = "RON",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            currency: Moneda contului de reclame. Decide in ce unitate se trimit
                bugetele - vezi :func:`minor_units_factor`. Implicit ``RON``
                (x100), corect si pentru EUR/USD; schimb-o daca contul e in
                HUF/JPY/etc., altfel bugetul ar pleca de 100 de ori mai mare.
            async_transport: Transportul pentru mutatii. Implicit il reia pe
                ``transport`` cand acela stie si async (``httpx.MockTransport``
                in teste), ca un singur argument sa acopere ambele cai.
        """
        self._access_token = access_token
        self._currency = currency
        self._timeout = timeout
        self._transport = transport
        if async_transport is None and isinstance(transport, httpx.AsyncBaseTransport):
            async_transport = transport
        self._async_transport = async_transport

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

    # --- mutatii (scriere pe contul real) -----------------------------------
    #
    # De aici incolo se schimba ceva intr-un cont pe care clientul plateste
    # bani. Toate trec prin _mutate, singurul loc care vorbeste in scriere cu
    # Graph API, ca taxonomia de erori sa fie una singura:
    #   - token expirat/revocat/fara permisiuni -> SetupRequiredError (se rezolva
    #     reconectand contul; reincercarea acum n-are sens);
    #   - orice refuz de continut (obiect inexistent, buget sub minim, campanie
    #     cu CBO) -> ProviderError cu mesajul EXACT de la Meta, nu parafrazat.
    # Motorul de executie le prinde pe amandoua si le scrie in error_message.

    async def _mutate(self, object_id: str, payload: dict[str, str]) -> dict[str, Any]:
        """Trimite un POST de modificare pe ``/{object_id}`` si valideaza raspunsul.

        Args:
            object_id: Id-ul obiectului Meta (campanie, set de reclame, anunt).
            payload: Campurile de schimbat, exact cum le asteapta Graph API.

        Returns:
            Corpul JSON al raspunsului (``{"success": true}`` de obicei).

        Raises:
            SetupRequiredError: token lipsa/expirat, sau Meta nu raspunde.
            ProviderError: Meta a refuzat schimbarea (mesajul ei, neschimbat).
        """
        if not object_id.strip():
            raise ProviderError("id de obiect Meta gol - nu am pe ce aplica schimbarea")
        headers = self._headers()
        url = f"{_BASE_URL}/{object_id}"
        try:
            async with httpx.AsyncClient(
                transport=self._async_transport, timeout=self._timeout
            ) as client:
                response = await client.post(url, data=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Meta Graph API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Meta Graph API nu a raspuns in {self._timeout:.0f}s."
            ) from exc

        try:
            data: dict[str, Any] = response.json()
        except ValueError:
            # Un 200 fara JSON nu s-a intalnit la Graph API, dar daca apare nu-l
            # tratam ca succes tacut - vezi verificarea de status de mai jos.
            data = {}
        error = data.get("error") or {}
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._mutation_error(response, error) from exc
        if error:
            # Meta poate raspunde 200 cu "error" in corp; nu e succes.
            raise self._mutation_error(response, error)
        return data

    def _mutation_error(
        self, response: httpx.Response, error: dict[str, Any]
    ) -> SetupRequiredError | ProviderError:
        """Traduce un refuz Meta in eroarea noastra, pastrandu-i mesajul."""
        message = str(error.get("message") or response.text[:200] or response.reason_phrase)
        if response.status_code in (401, 403) or error.get("code") in _AUTH_ERROR_CODES:
            return SetupRequiredError(
                f"Meta Graph API a refuzat autentificarea: {message}. "
                "Token-ul Meta e probabil expirat/revocat - reconecteaza contul."
            )
        return ProviderError(f"Meta Graph API a refuzat schimbarea: {message}")

    async def pause_campaign(self, campaign_id: str) -> None:
        """Pune pe pauza o campanie Meta.

        Args:
            campaign_id: Id-ul campaniei (numeric, cum il da Graph API).
        """
        await self._mutate(campaign_id, {"status": "PAUSED"})

    async def pause_adset(self, adset_id: str) -> None:
        """Pune pe pauza un set de reclame Meta.

        Args:
            adset_id: Id-ul setului de reclame (``arm_id`` din ``campaign_performance``).
        """
        await self._mutate(adset_id, {"status": "PAUSED"})

    async def pause_ad(self, ad_id: str) -> None:
        """Pune pe pauza un anunt Meta.

        Args:
            ad_id: Id-ul anuntului.

        La Graph API toate trei sunt acelasi apel (``POST /{id}`` cu
        ``status=PAUSED``); raman metode separate fiindca apelantul stie ce
        pune pe pauza, si un id de campanie trimis din greseala ca id de anunt
        trebuie sa se vada in cod, nu sa treaca tacut.
        """
        await self._mutate(ad_id, {"status": "PAUSED"})

    async def update_budget(self, object_id: str, new_daily_budget: Decimal) -> None:
        """Schimba bugetul zilnic al unei campanii sau al unui set de reclame.

        Args:
            object_id: Id-ul campaniei sau al setului de reclame.
            new_daily_budget: Noul buget zilnic, in moneda contului.

        Raises:
            ProviderError: buget negativ, sau Meta a refuzat (vezi mai jos).

        Meta refuza schimbarea, si e normal sa o faca, cand: suma e sub minimul
        ei pe moneda respectiva; obiectul are buget PE VIATA in loc de zilnic;
        sau setul de reclame e intr-o campanie cu buget la nivel de campanie
        (CBO), unde bugetul se schimba pe campanie, nu pe set. Mesajul ei ajunge
        neparafrazat in ``error_message``, ca omul sa stie care din cele trei e.
        """
        if new_daily_budget < 0:
            raise ProviderError(
                f"buget zilnic negativ ({new_daily_budget}) - Meta nu accepta asa ceva"
            )
        factor = minor_units_factor(self._currency)
        minor = (new_daily_budget * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        await self._mutate(object_id, {"daily_budget": str(minor)})
