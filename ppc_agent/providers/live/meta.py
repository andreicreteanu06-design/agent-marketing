"""Client live pentru Meta Marketing API (Graph API, REST simplu).

Acelasi pattern ca :mod:`ppc_agent.providers.live.google_ads` — ``httpx``
simplu, ``transport`` injectabil pentru teste deterministe. Fara SDK-ul oficial
``facebook-business`` (dependinta grea, inconsistenta cu restul codebase-ului).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

import httpx
import pandas as pd

from ppc_agent.errors import CampaignLaunchError, ProviderError, SetupRequiredError
from ppc_agent.providers.base import MetaMarketingProvider
from ppc_agent.providers.live.daily import DAILY_COLUMNS, daily_window
from ppc_agent.providers.meta_campaign import (
    LaunchResult,
    MetaLaunchSpec,
    ad_fields,
    adset_fields,
    campaign_fields,
    creative_fields,
    normalize_ad_account_id,
    video_fields,
)
from seo_geo_agent.audit import url_policy
from seo_geo_agent.audit.types import CRAWL_USER_AGENT

logger = logging.getLogger("ppc_agent.providers.live.meta")

_API_VERSION = "v25.0"  # Graph API - Meta reviseaza de ~2x/an.
_BASE_URL = f"https://graph.facebook.com/{_API_VERSION}"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGES = 20
#: Plafonul imaginii descarcate pentru anunt. Meta accepta pana la ~30 MB, dar o
#: imagine de reclama are rar peste cativa MB - iar descarcarea o facem noi, in
#: memorie, dintr-un URL venit din datele clientului.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
#: Cat asteptam ca Meta sa termine procesarea unui video urcat (intervale x incercari).
_VIDEO_POLL_SECONDS = 5.0
_VIDEO_POLL_ATTEMPTS = 24

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

# Meta raporteaza ACEEASI conversie sub mai multe tipuri de "actions": o cumparare
# de pe site apare si ca "purchase", si ca "omni_purchase", si ca
# "offsite_conversion.fb_pixel_purchase". Adunate, vanzarile si venitul ies dublate
# sau triplate - un cont pe pierdere arata rentabil. Din fiecare familie se ia
# DOAR primul tip prezent (agregatul, apoi variantele lui); cumpararile si lead-urile
# sunt evenimente diferite, deci familiile se aduna intre ele.
_CONVERSION_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"),
    ("lead", "offsite_conversion.fb_pixel_lead", "onsite_conversion.lead_grouped"),
)
# Doar conversiile de dupa un click, in 7 zile. Implicit Meta adauga si 1 zi dupa o
# simpla vizualizare (view-through), care umfla ROAS-ul cu vanzari pe care reclama
# nu le-a adus neaparat.
_ATTRIBUTION_WINDOW = "7d_click"
_INSIGHTS_ATTRIBUTION = json.dumps([_ATTRIBUTION_WINDOW])
#: Monitorul de oboseala judeca doar anunturile care ruleaza acum.
_ACTIVE_ADS = json.dumps([{"field": "ad.effective_status", "operator": "IN", "value": ["ACTIVE"]}])

# Vezi google_ads.py::_single_touch_paths - acelasi fallback (Meta Insights nu
# expune parcursuri multi-touch simplu), duplicat aici deliberat ca fiecare
# Live*Provider sa ramana auditabil de sine statator.
_MAX_PATHS_PER_ARM = 500


@dataclass(frozen=True, slots=True)
class AdDay:
    """O zi incheiata a unui anunt. Meta omite zilele fara livrare."""

    day: date
    spend: float
    impressions: int
    clicks: int
    conversions: float


@dataclass(frozen=True, slots=True)
class AdInsight:
    """Un anunt din contul Meta, pentru monitorul de oboseala.

    Cheltuiala, afisarile, click-urile, conversiile si venitul sunt de la lansare;
    ``days`` sunt ultimele zile incheiate. Un anunt care nu ruleaza (``active`` fals)
    vine fara cifre: nu mai e nimic de judecat la el.
    """

    ad_id: str
    name: str
    created_time: datetime
    active: bool
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    revenue: float = 0.0
    frequency_7d: float = 0.0
    #: Vizionarile de 3 secunde (``video_view``), de la lansare; 0 la imagini.
    video_views: int = 0
    days: tuple[AdDay, ...] = ()


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


def _counted(actions: list[dict[str, Any]] | None) -> float:
    """Suma unei liste ``actions``/``action_values``, o singura data pe conversie."""
    by_type = {
        str(action.get("action_type")): float(
            action.get(_ATTRIBUTION_WINDOW, action.get("value", 0))
        )
        for action in actions or []
    }
    return sum(
        next((by_type[kind] for kind in family if kind in by_type), 0.0)
        for family in _CONVERSION_FAMILIES
    )


def _video_views(row: dict[str, Any]) -> int:
    """Vizionarile de 3 secunde dintr-un rand Insights (actiunea ``video_view``)."""
    return sum(
        round(float(action.get("value", 0)))
        for action in row.get("actions") or []
        if action.get("action_type") == "video_view"
    )


def _conversion_totals(row: dict[str, Any]) -> tuple[float, float]:
    """Conversiile si venitul unui rand Insights, fiecare conversie numarata o data.

    Folosit si de agregatul pe 30 de zile, si de citirea zilnica, si de lichiditate -
    aceeasi definitie a "conversiei", ca raportul sa nu contrazica planul de buget.
    """
    return _counted(row.get("actions")), _counted(row.get("action_values"))


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


def to_minor_units(amount: Decimal, currency: str) -> int:
    """Suma in unitatea minima a monedei, cum o cere Graph API (25.50 RON -> 2550).

    Singurul loc din cod care face conversia - si actualizarea de buget, si
    lansarea de campanii trec pe aici, ca doua rotunjiri sa nu poata diverge.
    """
    factor = minor_units_factor(currency)
    return int((amount * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _created_id(response: dict[str, Any], what: str) -> str:
    value = response.get("id")
    if not value:
        raise ProviderError(f"Meta a raspuns fara id la crearea {what}: {str(response)[:200]}")
    return str(value)


def _image_hash(response: dict[str, Any]) -> str:
    """Hash-ul din raspunsul ``/adimages``: ``{"images": {"<cheie>": {"hash": ...}}}``."""
    images = response.get("images")
    if isinstance(images, dict):
        for entry in images.values():
            if isinstance(entry, dict) and entry.get("hash"):
                return str(entry["hash"])
    raise ProviderError(f"Meta nu a intors hash-ul imaginii: {str(response)[:200]}")


_NOTHING_CREATED = "Nimic nu a fost creat in contul Meta."


async def download_image(
    image_url: str,
    *,
    max_bytes: int = _MAX_IMAGE_BYTES,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bytes:
    """Imaginea anuntului, descarcata de noi si verificata - vezi :func:`download_media`."""
    return await download_media(
        image_url, kind="image", max_bytes=max_bytes, transport=transport, timeout=timeout
    )


async def download_media(
    url: str,
    *,
    kind: Literal["image", "video", "any"],
    max_bytes: int,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    probe: bool = False,
) -> bytes:
    """Un fisier al anuntului (imagine sau video), descarcat de noi si verificat.

    URL-ul vine din datele clientului, deci se valideaza ca orice tinta
    nesigura: fara adrese interne, nici directe, nici prin DNS (acelasi
    filtru ca la crawler-ul de audit). Redirecturile NU se urmaresc - un
    salt ar putea duce exact unde validarea n-a verificat.

    Limita cunoscuta, aceeasi ca la crawler: DNS-ul se rezolva o data la
    validare si inca o data la cerere, deci un DNS ostil ar putea raspunde
    diferit intre ele.

    Args:
        kind: Ce tip de continut se accepta (``any`` = imagine sau video).
        probe: Doar verifica (raspuns 200, tipul corect) si returneaza ``b""`` fara
            sa citeasca fisierul - pentru un video pe care Meta il descarca singura.

    Raises:
        ProviderError: URL refuzat, raspuns ne-200, alt tip de continut, sau peste plafon.
    """
    noun = {"image": "imaginea", "video": "video-ul", "any": "fisierul"}[kind]
    accepted = {"image": ("image/",), "video": ("video/",), "any": ("image/", "video/")}[kind]
    try:
        # Rezultatul (URL-ul normalizat) se arunca DELIBERAT: normalizarea
        # sorteaza parametrii din query, ceea ce strica URL-urile semnate
        # ale CDN-urilor. Validam gazda, dar cerem URL-ul exact.
        await url_policy.normalize_and_validate_start_url(url)
    except (ValueError, url_policy.CrawlTargetBlockedError) as exc:
        raise ProviderError(
            f"{noun} nu se poate descarca de la '{url}': adresa refuzata ({exc})"
        ) from exc

    chunks: list[bytes] = []
    try:
        async with (
            httpx.AsyncClient(
                transport=transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client,
            client.stream("GET", url, headers={"User-Agent": CRAWL_USER_AGENT}) as response,
        ):
            if 300 <= response.status_code < 400:
                raise ProviderError(
                    f"URL-ul pentru {noun} redirectioneaza ({response.status_code}) - "
                    "foloseste adresa finala a fisierului"
                )
            if response.status_code != 200:
                raise ProviderError(f"{noun} de la '{url}' a raspuns {response.status_code}")
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith(accepted):
                what = {"image": "o imagine", "video": "un video", "any": "o imagine sau un video"}
                raise ProviderError(
                    f"'{url}' nu e {what[kind]} (content-type '{content_type or 'lipsa'}')"
                )
            if probe:
                return b""
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ProviderError(f"{noun} depaseste {max_bytes // (1024 * 1024)} MB")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{noun} de la '{url}' nu a putut fi descarcat: {exc}") from exc

    data = b"".join(chunks)
    if not data:
        raise ProviderError(f"{noun} de la '{url}' e gol")
    return data


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
        video_poll_seconds: float = _VIDEO_POLL_SECONDS,
        video_poll_attempts: int = _VIDEO_POLL_ATTEMPTS,
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
        self._video_poll_seconds = video_poll_seconds
        self._video_poll_attempts = video_poll_attempts

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
            {"fields": "id,name,targeting,learning_stage_info,daily_budget", "limit": 200},
        )
        insights = self._paginate(
            f"{ad_account_id}/insights",
            {
                "level": "adset",
                "date_preset": "last_7d",
                "fields": "adset_id,spend,actions",
                "action_attribution_windows": _INSIGHTS_ATTRIBUTION,
                "limit": 200,
            },
        )
        insight_by_id = {str(row["adset_id"]): row for row in insights if "adset_id" in row}

        rows: list[dict[str, Any]] = []
        for adset in adsets:
            adset_id = str(adset.get("id", ""))
            insight = insight_by_id.get(adset_id, {})
            weekly_conversions = _counted(insight.get("actions"))
            learning_status = str((adset.get("learning_stage_info") or {}).get("status", ""))
            # In unitatea minima a monedei (bani), ca la scriere; lipseste cand bugetul
            # e pe campanie (CBO).
            raw_budget = adset.get("daily_budget")
            daily_budget = (
                float(Decimal(str(raw_budget)) / minor_units_factor(self._currency))
                if raw_budget not in (None, "", "0")
                else None
            )
            rows.append(
                {
                    "ad_set_id": adset_id,
                    "name": str(adset.get("name", "")),
                    "audience_def": _summarize_targeting(adset.get("targeting") or {}),
                    "weekly_conversions": weekly_conversions,
                    "weekly_spend": float(insight.get("spend", 0.0)),
                    "learning_phase": learning_status in _LEARNING_STATUSES,
                    "learning_status": learning_status,
                    "daily_budget": daily_budget,
                }
            )
        columns = [
            "ad_set_id",
            "name",
            "audience_def",
            "weekly_conversions",
            "weekly_spend",
            "learning_phase",
            "learning_status",
            "daily_budget",
        ]
        return pd.DataFrame(rows, columns=columns)

    def campaign_performance(self, ad_account_id: str) -> pd.DataFrame:
        """Performanta pe seturi de reclame (30 de zile), pentru Modulul 2 (bandit).

        ``active``: setul ruleaza acum. Insights intoarce si seturile oprite care au
        cheltuit in fereastra - istoricul lor conteaza (CFO-ul), bugetul nu.
        """
        running = {
            str(adset.get("id", ""))
            for adset in self._paginate(
                f"{ad_account_id}/adsets", {"fields": "id,effective_status", "limit": 200}
            )
            if adset.get("effective_status") == "ACTIVE"
        }
        insights = self._paginate(
            f"{ad_account_id}/insights",
            {
                "level": "adset",
                "date_preset": "last_30d",
                "fields": "adset_id,adset_name,clicks,spend,actions,action_values",
                "action_attribution_windows": _INSIGHTS_ATTRIBUTION,
                "limit": 200,
            },
        )
        out: list[dict[str, Any]] = []
        for row in insights:
            try:
                conversions, revenue = _conversion_totals(row)
                out.append(
                    {
                        "arm_id": str(row["adset_id"]),
                        "name": str(row.get("adset_name", row["adset_id"])),
                        "clicks": int(row.get("clicks", 0)),
                        "conversions": round(conversions),
                        "cost": float(row.get("spend", 0.0)),
                        "revenue": revenue,
                        "active": str(row["adset_id"]) in running,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(f"rand Meta Insights cu forma neasteptata: {exc}") from exc
        columns = ["arm_id", "name", "clicks", "conversions", "cost", "revenue", "active"]
        return pd.DataFrame(out, columns=columns)

    def daily_campaign_performance(
        self, ad_account_id: str, *, days: int, end_date: date | None = None
    ) -> pd.DataFrame:
        """Performanta pe seturi de reclame, zi cu zi (Insights cu ``time_increment=1``).

        Args:
            ad_account_id: Contul de reclame (``act_...``).
            days: Cate zile, numarate inapoi de la ``end_date`` inclusiv.
            end_date: Ultima zi inclusa; implicit ieri.

        Returns:
            Aceleasi coloane ca :meth:`campaign_performance`, plus ``date``;
            conversiile raman fractionare, ca la Google Ads.

        Meta omite zilele fara livrare - apelantul le completeaza cu zero.
        """
        start, end = daily_window(days, end_date)
        insights = self._paginate(
            f"{ad_account_id}/insights",
            {
                "level": "adset",
                "time_increment": 1,
                "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
                "fields": "adset_id,adset_name,clicks,spend,actions,action_values",
                "action_attribution_windows": _INSIGHTS_ATTRIBUTION,
                "limit": 500,
            },
        )
        out: list[dict[str, Any]] = []
        for row in insights:
            try:
                conversions, revenue = _conversion_totals(row)
                out.append(
                    {
                        "date": date.fromisoformat(str(row["date_start"])),
                        "arm_id": str(row["adset_id"]),
                        "name": str(row.get("adset_name", row["adset_id"])),
                        "clicks": int(row.get("clicks", 0)),
                        "conversions": conversions,
                        "cost": float(row.get("spend", 0.0)),
                        "revenue": revenue,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"rand zilnic Meta Insights cu forma neasteptata: {exc}"
                ) from exc
        return pd.DataFrame(out, columns=DAILY_COLUMNS)

    def ad_insights(self, ad_account_id: str, *, days: int = 14) -> list[AdInsight]:
        """Anunturile contului, pentru monitorul de oboseala din jobul de noapte.

        Lista anunturilor (starea, data lansarii), apoi - doar pentru cele active -
        cifrele de la lansare, frecventa pe 7 zile si ultimele ``days`` zile incheiate.
        Conversiile se numara ca peste tot: o data, in 7 zile dupa click.
        """
        ads = self._paginate(
            f"{ad_account_id}/ads",
            {"fields": "id,name,created_time,effective_status", "limit": 200},
        )
        insights = f"{ad_account_id}/insights"
        base = {"level": "ad", "filtering": _ACTIVE_ADS, "limit": 500}
        counted = {"action_attribution_windows": _INSIGHTS_ATTRIBUTION}
        lifetime = {
            str(row["ad_id"]): row
            for row in self._paginate(
                insights,
                {
                    **base,
                    **counted,
                    "date_preset": "maximum",
                    "fields": "ad_id,spend,impressions,clicks,actions,action_values",
                },
            )
        }
        week = {
            str(row["ad_id"]): row
            for row in self._paginate(
                insights, {**base, "date_preset": "last_7d", "fields": "ad_id,frequency"}
            )
        }
        start, end = daily_window(days, None)
        by_day: dict[str, list[AdDay]] = {}
        try:
            for row in self._paginate(
                insights,
                {
                    **base,
                    **counted,
                    "time_increment": 1,
                    "time_range": json.dumps(
                        {"since": start.isoformat(), "until": end.isoformat()}
                    ),
                    "fields": "ad_id,date_start,spend,impressions,clicks,actions",
                },
            ):
                by_day.setdefault(str(row["ad_id"]), []).append(
                    AdDay(
                        day=date.fromisoformat(str(row["date_start"])),
                        spend=float(row.get("spend", 0.0)),
                        impressions=int(row.get("impressions", 0)),
                        clicks=int(row.get("clicks", 0)),
                        conversions=_conversion_totals(row)[0],
                    )
                )
            out: list[AdInsight] = []
            for ad in ads:
                ad_id = str(ad["id"])
                name = str(ad.get("name", ad_id))
                created = datetime.strptime(str(ad["created_time"]), "%Y-%m-%dT%H:%M:%S%z")
                if ad.get("effective_status") != "ACTIVE":
                    out.append(
                        AdInsight(ad_id=ad_id, name=name, created_time=created, active=False)
                    )
                    continue
                row = lifetime.get(ad_id, {})
                conversions, revenue = _conversion_totals(row)
                out.append(
                    AdInsight(
                        ad_id=ad_id,
                        name=name,
                        created_time=created,
                        active=True,
                        spend=float(row.get("spend", 0.0)),
                        impressions=int(row.get("impressions", 0)),
                        clicks=int(row.get("clicks", 0)),
                        conversions=conversions,
                        revenue=revenue,
                        frequency_7d=float(week.get(ad_id, {}).get("frequency", 0.0)),
                        video_views=_video_views(row),
                        days=tuple(sorted(by_day.get(ad_id, []), key=lambda day: day.day)),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"anunt Meta cu forma neasteptata: {exc}") from exc
        return out

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
    # bani. Toate scrierile trec prin _mutate/_delete si sunt interpretate de
    # _checked - un singur loc, ca taxonomia de erori sa fie una singura:
    #   - token expirat/revocat/fara permisiuni -> SetupRequiredError (se rezolva
    #     reconectand contul; reincercarea acum n-are sens);
    #   - orice refuz de continut (obiect inexistent, buget sub minim, campanie
    #     cu CBO) -> ProviderError cu mesajul EXACT de la Meta, nu parafrazat.
    # Motorul de executie le prinde pe amandoua si le scrie in error_message.

    async def _mutate(self, object_id: str, payload: dict[str, str]) -> dict[str, Any]:
        """Trimite un POST pe ``/{object_id}`` si valideaza raspunsul.

        Args:
            object_id: Id-ul obiectului Meta, sau o cale de creare
                (``act_123/campaigns``).
            payload: Campurile, exact cum le asteapta Graph API.

        Returns:
            Corpul JSON al raspunsului (``{"success": true}`` sau ``{"id": ...}``).

        Raises:
            SetupRequiredError: token lipsa/expirat, sau Meta nu raspunde.
            ProviderError: Meta a refuzat (mesajul ei, neschimbat).
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
        return self._checked(response)

    async def _get(self, object_id: str, params: dict[str, str]) -> dict[str, Any]:
        """``GET /{object_id}`` asincron - folosit de lansare (starea unui video urcat)."""
        headers = self._headers()
        url = f"{_BASE_URL}/{object_id}"
        try:
            async with httpx.AsyncClient(
                transport=self._async_transport, timeout=self._timeout
            ) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Meta Graph API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Meta Graph API nu a raspuns in {self._timeout:.0f}s."
            ) from exc
        return self._checked(response)

    async def _wait_video_ready(self, video_id: str) -> None:
        """Asteapta pana cand Meta termina procesarea video-ului urcat.

        Raises:
            ProviderError: Meta raporteaza eroare, sau video-ul nu e gata dupa
                ``video_poll_attempts`` verificari.
        """
        for attempt in range(self._video_poll_attempts):
            data = await self._get(video_id, {"fields": "status"})
            status = str((data.get("status") or {}).get("video_status", ""))
            if status == "ready":
                return
            if status == "error":
                raise ProviderError(f"Meta nu a putut procesa video-ul {video_id}")
            if attempt + 1 < self._video_poll_attempts:
                await asyncio.sleep(self._video_poll_seconds)
        waited = self._video_poll_seconds * self._video_poll_attempts
        raise ProviderError(f"video-ul {video_id} nu s-a procesat in {waited:.0f} s")

    async def _delete(self, object_id: str) -> None:
        """``DELETE /{object_id}`` - folosit doar de rollback-ul lansarii."""
        headers = self._headers()
        url = f"{_BASE_URL}/{object_id}"
        try:
            async with httpx.AsyncClient(
                transport=self._async_transport, timeout=self._timeout
            ) as client:
                response = await client.delete(url, headers=headers)
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Meta Graph API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Meta Graph API nu a raspuns in {self._timeout:.0f}s."
            ) from exc
        self._checked(response)

    def _checked(self, response: httpx.Response) -> dict[str, Any]:
        """Corpul unui raspuns de scriere, sau refuzul Meta tradus in eroarea noastra."""
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
        """Traduce un refuz Meta in eroarea noastra, pastrandu-i mesajul.

        ``message`` e deseori generic ("Invalid parameter"); motivul pe care il
        poate repara un om sta in ``error_user_msg``. Le pastram pe amandoua,
        neparafrazate.
        """
        message = str(error.get("message") or response.text[:200] or response.reason_phrase)
        user_msg = error.get("error_user_msg")
        if user_msg:
            title = error.get("error_user_title")
            message = f"{message} ({title}: {user_msg})" if title else f"{message} ({user_msg})"
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

    async def current_daily_budget(self, object_id: str) -> Decimal | None:
        """Bugetul zilnic de acum al unei campanii sau al unui set, in moneda contului.

        Citit chiar inainte de o schimbare de buget: motorul de executie lasa peste
        plafon doar o reducere fata de el. ``None`` cand obiectul n-are buget zilnic
        (buget pe viata, sau set dintr-o campanie cu buget pe campanie).
        """
        headers = self._headers()
        try:
            async with httpx.AsyncClient(
                transport=self._async_transport, timeout=self._timeout
            ) as client:
                response = await client.get(
                    f"{_BASE_URL}/{object_id}", params={"fields": "daily_budget"}, headers=headers
                )
        except httpx.ConnectError as exc:
            raise SetupRequiredError(f"Meta Graph API nu raspunde la {_BASE_URL}.") from exc
        except httpx.TimeoutException as exc:
            raise SetupRequiredError(
                f"Meta Graph API nu a raspuns in {self._timeout:.0f}s."
            ) from exc
        raw = self._checked(response).get("daily_budget")
        if raw in (None, "", "0"):
            return None
        return Decimal(str(raw)) / minor_units_factor(self._currency)

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
        minor = to_minor_units(new_daily_budget, self._currency)
        await self._mutate(object_id, {"daily_budget": str(minor)})

    # --- lansarea unei campanii noi ------------------------------------------
    #
    # Ajunge aici DOAR dupa aprobarea umana a unei propuneri CREATE_CAMPAIGN
    # (vezi services/execution_engine.py). Payload-urile le construiesc functiile
    # pure din providers/meta_campaign.py; aici stau doar ordinea apelurilor,
    # conversia bugetului si rollback-ul.

    async def _download_image(self, image_url: str) -> bytes:
        """Imaginea anuntului - vezi :func:`download_image`."""
        return await download_image(
            image_url, transport=self._async_transport, timeout=self._timeout
        )

    async def _rollback(self, campaign_id: str) -> tuple[bool, str]:
        """Sterge campania creata in aceasta lansare.

        Returns:
            ``(reusit, ce s-a intamplat)`` - textul ajunge in ``error_message``.

        Stergerea campaniei ia cu ea ad set-urile si anunturile de sub ea.
        Imaginea si creative-ul raman in biblioteca contului: singure nu pot
        cheltui nimic, deci nu merita un al doilea punct de esec aici.
        Nu ridica exceptii - un rollback esuat trebuie RAPORTAT, nu sa ascunda
        eroarea initiala.
        """
        try:
            await self._delete(campaign_id)
        except Exception as exc:
            logger.error(
                "ROLLBACK ESUAT: campania %s poate sa fi ramas in cont: %s", campaign_id, exc
            )
            return False, (
                f"ATENTIE: rollback-ul a esuat ({exc}) - campania {campaign_id} poate sa fi "
                "ramas in cont, OPRITA (PAUSED). Verifica in Ads Manager si sterge-o manual "
                "daca exista."
            )
        return True, f"Campania {campaign_id} a fost stearsa (rollback), cu tot ce era sub ea."

    async def launch_campaign(self, ad_account_id: str, spec: MetaLaunchSpec) -> LaunchResult:
        """Creeaza o campanie de conversii completa, totul OPRIT (PAUSED).

        Args:
            ad_account_id: Contul de reclame (``act_123`` sau ``123``).
            spec: Specificatia aprobata - exact cea din propunere.

        Returns:
            Id-urile tuturor obiectelor create.

        Raises:
            CampaignLaunchError: un pas a picat. Mesajul spune pasul, eroarea
                exacta de la Meta si ce a ramas in cont dupa rollback.

        Ordinea:

        0. imaginile tuturor reclamelor se descarca de la noi, iar URL-urile video
           se verifica - INAINTE de orice apel Meta, ca un URL stricat sa nu lase in
           urma o campanie de sters;
        1. campania; 2. ad set-ul (bugetul se converteste in unitati minime
           ABIA acum, dupa moneda contului); apoi, pentru fiecare reclama:
           3. imaginea (la video, coperta) urcata in Meta; la video, si video-ul,
           asteptat pana e procesat; 4. creative-ul; 5. anuntul.

        Daca pica ceva dupa pasul 1, campania se sterge - altfel fiecare
        incercare esuata ar lasa resturi in contul clientului.
        """
        account = normalize_ad_account_id(ad_account_id)
        try:
            images = [await self._download_image(ad.image_url) for ad in spec.ads]
            for ad in spec.ads:
                if ad.video_url:
                    # Meta descarca video-ul singura; noi verificam doar ca exista si e video.
                    await download_media(
                        ad.video_url,
                        kind="video",
                        max_bytes=0,
                        transport=self._async_transport,
                        timeout=self._timeout,
                        probe=True,
                    )
        except ProviderError as exc:
            raise CampaignLaunchError(
                stage="image_download", reason=str(exc), outcome=_NOTHING_CREATED
            ) from exc

        try:
            campaign_id = _created_id(
                await self._mutate(f"{account}/campaigns", campaign_fields(spec)), "campaniei"
            )
        except Exception as exc:
            # Un timeout NU inseamna "nu s-a creat": Meta poate crea campania si
            # sa piarda raspunsul pe drum. Nu stim - si o spunem.
            outcome = (
                "Rezultat NECUNOSCUT: Meta nu a raspuns la timp, deci campania "
                f"'{spec.campaign_name}' poate exista totusi. Verifica in Ads Manager "
                "inainte sa propui lansarea din nou."
                if isinstance(exc.__cause__, httpx.TimeoutException)
                else _NOTHING_CREATED
            )
            raise CampaignLaunchError(stage="campaign", reason=str(exc), outcome=outcome) from exc

        stage = "adset"
        try:
            budget_minor = to_minor_units(spec.daily_budget, self._currency)
            adset_id = _created_id(
                await self._mutate(
                    f"{account}/adsets",
                    adset_fields(spec, campaign_id=campaign_id, daily_budget_minor=budget_minor),
                ),
                "setului de reclame",
            )
            launched: list[tuple[str, str, str]] = []
            for index, (ad, image) in enumerate(zip(spec.ads, images, strict=True)):
                stage = "image_upload"
                image_hash = _image_hash(
                    await self._mutate(
                        f"{account}/adimages",
                        {"bytes": base64.b64encode(image).decode("ascii")},
                    )
                )
                video_id: str | None = None
                if ad.video_url:
                    stage = "video_upload"
                    video_id = _created_id(
                        await self._mutate(
                            f"{account}/advideos", video_fields(spec, ad, index=index)
                        ),
                        "video-ului",
                    )
                    stage = "video_processing"
                    await self._wait_video_ready(video_id)
                stage = "creative"
                creative_id = _created_id(
                    await self._mutate(
                        f"{account}/adcreatives",
                        creative_fields(
                            spec, image_hash=image_hash, ad=ad, index=index, video_id=video_id
                        ),
                    ),
                    "creative-ului",
                )
                stage = "ad"
                ad_id = _created_id(
                    await self._mutate(
                        f"{account}/ads",
                        ad_fields(spec, adset_id=adset_id, creative_id=creative_id, index=index),
                    ),
                    "anuntului",
                )
                launched.append((image_hash, creative_id, ad_id))
        except Exception as exc:
            rolled_back, outcome = await self._rollback(campaign_id)
            raise CampaignLaunchError(
                stage=stage,
                reason=str(exc),
                outcome=outcome,
                campaign_id=campaign_id,
                rolled_back=rolled_back,
            ) from exc

        image_hash, creative_id, ad_id = launched[0]
        logger.info(
            "campanie lansata OPRITA in %s: campanie %s, set %s, %d anunturi (primul %s)",
            account,
            campaign_id,
            adset_id,
            len(launched),
            ad_id,
        )
        return LaunchResult(
            campaign_id=campaign_id,
            adset_id=adset_id,
            image_hash=image_hash,
            creative_id=creative_id,
            ad_id=ad_id,
            extra_ad_ids=tuple(ad for _, _, ad in launched[1:]),
        )
