"""Adresa afacerii -> coordonate si marimea localitatii (OpenStreetMap / Nominatim).

Gratuit, fara cheie. Politica Nominatim: un ``User-Agent`` care identifica aplicatia si
cel mult o cerere pe secunda - aici sunt doua cereri per adresa, si doar cand clientul
isi da adresa in chat, deci departe de limita.

Doua cereri: adresa exacta (coordonatele si localitatea ei), apoi localitatea (populatia,
din ``extratags``) - de ea depinde raza: intr-un sat, o raza mica n-ar avea cui sa arate
reclama.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from ppc_agent.client_economics import PlaceSize, place_size
from ppc_agent.errors import ProviderError

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ac-media-ppc-agent/1.0 (consiliul PPC: raza reclamelor locale)"
_TIMEOUT = 10.0
_COORDINATE = Decimal("0.000001")
#: Cheile ``address`` ale Nominatim pentru localitate, de la cea mai mare la cea mai mica.
_LOCALITY_KEYS = ("city", "town", "municipality", "village", "hamlet")


@dataclass(frozen=True, slots=True)
class Place:
    latitude: Decimal
    longitude: Decimal
    label: str
    locality: str
    size: PlaceSize


#: ``(adresa, cod de tara ISO) -> locul``, sau ``None`` cand adresa nu exista.
Geocoder = Callable[[str, str], "Place | None"]


def _search(params: dict[str, str], transport: httpx.BaseTransport | None) -> list[dict[str, Any]]:
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            response = client.get(
                NOMINATIM_URL,
                params={"format": "jsonv2", "limit": "1", **params},
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"harta (Nominatim) nu raspunde: {type(exc).__name__}") from exc
    if response.is_error:
        raise ProviderError(f"harta (Nominatim) a raspuns cu eroarea {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError("raspuns Nominatim invalid") from exc
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def nominatim_geocode(
    address: str, country: str, *, transport: httpx.BaseTransport | None = None
) -> Place | None:
    """Locul ``address`` din ``country``; ``None`` cand harta nu o gaseste.

    Raises:
        ProviderError: harta nu raspunde.
    """
    country_code = country.strip().lower() or "ro"
    found = _search({"q": address, "countrycodes": country_code, "addressdetails": "1"}, transport)
    if not found:
        return None
    hit = found[0]
    parts = hit.get("address") or {}
    locality_key = next((key for key in _LOCALITY_KEYS if parts.get(key)), "")
    locality = str(parts.get(locality_key, ""))
    population: int | None = None
    if locality:
        town = _search(
            {"city": locality, "countrycodes": country_code, "extratags": "1"}, transport
        )
        raw = ((town[0].get("extratags") or {}) if town else {}).get("population")
        try:
            population = int(str(raw).replace(".", "").replace(" ", "")) if raw else None
        except ValueError:
            population = None
    try:
        latitude = Decimal(str(hit["lat"])).quantize(_COORDINATE)
        longitude = Decimal(str(hit["lon"])).quantize(_COORDINATE)
    except (KeyError, ArithmeticError) as exc:
        raise ProviderError("raspuns Nominatim fara coordonate") from exc
    return Place(
        latitude=latitude,
        longitude=longitude,
        label=str(hit.get("display_name", address))[:300],
        locality=locality,
        size=place_size(population, "city" if locality_key == "city" else locality_key),
    )
