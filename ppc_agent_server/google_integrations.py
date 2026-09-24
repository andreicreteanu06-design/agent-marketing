"""Integrarile Google ale unui client: Search Console si Google Analytics 4.

Separat de router ca sa poata fi testat fara HTTP: ce scope cere fiecare
integrare, in ce campuri ale ``ClientAccount`` se salveaza, cum se listeaza
proprietatile din contul Google si ce forma are un ID valid.

Clientul OAuth (``PPC_GOOGLE_OAUTH_CLIENT_ID/SECRET``) e ACELASI cu care
agentul reimprospateaza apoi token-urile (``jobs/tasks.py::_app_config_for``):
un refresh token Google se poate folosi doar cu clientul OAuth care l-a emis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ppc_agent.config import Settings
from ppc_agent.errors import ProviderError
from ppc_agent.search_data.google_oauth import ANALYTICS_SCOPE, SEARCH_CONSOLE_SCOPE

IntegrationName = Literal["gsc", "ga4"]

_GSC_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
_GA4_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
#: Cate pagini de conturi GA4 citim. 200 de conturi pe pagina - peste 5 pagini
#: nu mai e o lista din care alege un om.
_MAX_GA4_PAGES = 5
#: Nivelul de acces cu care Search Console nu da date - nu are rost afisat.
_GSC_UNVERIFIED = "siteUnverifiedUser"

_GA4_PROPERTY_ID = re.compile(r"(?:properties/)?(\d{1,20})")
_GSC_DOMAIN_PROPERTY = re.compile(r"sc-domain:[a-z0-9.-]+\.[a-z0-9-]+")
_GSC_URL_PROPERTY = re.compile(r"(https?://[^\s/]+\.[^\s/]+)(/\S*)?")


@dataclass(frozen=True, slots=True)
class GoogleIntegration:
    """Ce inseamna o integrare: scope-ul cerut si unde se salveaza pe cont."""

    name: IntegrationName
    label: str
    scopes: tuple[str, ...]
    #: Campul criptat de pe ``ClientAccount`` cu refresh token-ul.
    token_field: str
    #: Campul de pe ``ClientAccount`` cu proprietatea aleasa.
    property_field: str


INTEGRATIONS: dict[IntegrationName, GoogleIntegration] = {
    # Doar Search Console, fara 'business.manage': acela e un drept de
    # ADMINISTRARE a profilului de firma, iar Business Profile ruleaza oricum
    # doar cu o locatie configurata global (vezi launch_brief.py).
    "gsc": GoogleIntegration(
        name="gsc",
        label="Google Search Console",
        scopes=(SEARCH_CONSOLE_SCOPE,),
        token_field="gsc_refresh_token_enc",
        property_field="gsc_site_url",
    ),
    "ga4": GoogleIntegration(
        name="ga4",
        label="Google Analytics 4",
        scopes=(ANALYTICS_SCOPE,),
        token_field="ga4_refresh_token_enc",
        property_field="ga4_property_id",
    ),
}


@dataclass(frozen=True, slots=True)
class GoogleOAuthClient:
    """Clientul OAuth "Web application" din Google Cloud Console."""

    client_id: str
    client_secret: str


def google_oauth_client() -> GoogleOAuthClient | None:
    """Clientul OAuth din ``.env`` (``PPC_GOOGLE_OAUTH_*``) sau ``None`` daca lipseste."""
    settings = Settings()
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        return None
    return GoogleOAuthClient(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
    )


@dataclass(frozen=True, slots=True)
class PropertyOption:
    """O proprietate din contul Google, gata de ales dintr-o lista."""

    id: str
    label: str


def normalize_property_id(integration: GoogleIntegration, raw: str) -> str:
    """Proprietatea in forma exacta ceruta de API-ul Google.

    GA4 accepta si ``properties/123`` (forma din Admin API) si ``123``; se
    salveaza doar cifrele. Search Console cere forma exacta din interfata:
    ``sc-domain:exemplu.ro`` sau un prefix URL - un domeniu gol ar fi o
    ghicitoare despre tipul proprietatii.

    Raises:
        ValueError: forma nu corespunde, cu un mesaj pentru client.
    """
    value = raw.strip()
    if integration.name == "ga4":
        match = _GA4_PROPERTY_ID.fullmatch(value)
        if match is None:
            raise ValueError(
                "ID-ul proprietatii GA4 e numeric (ex. 123456789), din Admin -> "
                "Property settings. 'G-...' e ID-ul fluxului de date, nu al proprietatii."
            )
        return match.group(1)
    if _GSC_DOMAIN_PROPERTY.fullmatch(value.lower()):
        return value.lower()
    url_match = _GSC_URL_PROPERTY.fullmatch(value)
    if url_match is not None:
        # Proprietatile de tip prefix URL se termina mereu in '/' in Search Console.
        return url_match.group(1) + (url_match.group(2) or "/")
    raise ValueError(
        "Proprietatea Search Console se scrie exact ca in Search Console: "
        "'sc-domain:exemplu.ro' sau 'https://www.exemplu.ro/'."
    )


def _get_json(
    url: str,
    access_token: str,
    *,
    params: dict[str, str] | None,
    transport: httpx.BaseTransport | None,
    timeout: float,
) -> dict[str, Any]:
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Google nu a raspuns ({url}): {exc}") from exc
    if response.status_code >= 400:
        raise ProviderError(
            f"Google a refuzat lista de proprietati ({response.status_code}): "
            f"{response.text[:200]}"
        )
    body = response.json()
    return body if isinstance(body, dict) else {}


def _gsc_label(site_url: str) -> str:
    if site_url.startswith("sc-domain:"):
        return f"{site_url.removeprefix('sc-domain:')} (tot domeniul)"
    return site_url


def list_properties(
    integration: GoogleIntegration,
    access_token: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> list[PropertyOption]:
    """Proprietatile la care are acces contul Google conectat.

    Raises:
        ProviderError: Google a refuzat cererea sau a raspuns cu o eroare
            (de ex. Google Analytics Admin API neactivat in proiectul Cloud).
    """
    if integration.name == "gsc":
        body = _get_json(
            _GSC_SITES_URL, access_token, params=None, transport=transport, timeout=timeout
        )
        return [
            PropertyOption(id=entry["siteUrl"], label=_gsc_label(entry["siteUrl"]))
            for entry in body.get("siteEntry", [])
            if entry.get("siteUrl") and entry.get("permissionLevel") != _GSC_UNVERIFIED
        ]

    options: list[PropertyOption] = []
    page_token = ""
    for _ in range(_MAX_GA4_PAGES):
        params = {"pageSize": "200"}
        if page_token:
            params["pageToken"] = page_token
        body = _get_json(
            _GA4_ACCOUNT_SUMMARIES_URL,
            access_token,
            params=params,
            transport=transport,
            timeout=timeout,
        )
        for account in body.get("accountSummaries", []):
            account_name = account.get("displayName", "")
            for summary in account.get("propertySummaries", []):
                property_id = str(summary.get("property", "")).removeprefix("properties/")
                if not property_id:
                    continue
                name = summary.get("displayName") or property_id
                label = f"{name} · {account_name}" if account_name else name
                options.append(PropertyOption(id=property_id, label=label))
        page_token = body.get("nextPageToken", "")
        if not page_token:
            break
    return options
