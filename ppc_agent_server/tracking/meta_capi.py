"""Trimiterea conversiilor calificate catre Meta Conversions API (CAPI).

De ce conteaza ``event_id``: aceeasi achizitie ajunge la Meta de doua ori - o
data din pixelul din browser, o data de aici. Meta le contopeste doar daca au
acelasi ``event_name`` si acelasi ``event_id``; altfel o vanzare devine doua,
iar Meta (si Thompson/Markov, care citesc rezultatele) optimizeaza pe date
dublate. Pe site, pixelul trebuie sa trimita deci exact id-ul nostru:
``fbq('track', 'Purchase', {...}, {eventID: 'gomag_order_1001'})``.

Ce pleaca: doar conversiile CALIFICATE (un apel de 10 secunde nu e un lead -
Meta n-are ce invata din el), cu PII-ul deja hash-uit (SHA-256) din baza de
date. Un lead calificat pleaca de doua ori: ``Lead`` (contopit cu pixelul, care il
trimite la ORICE formular) si :data:`QUALIFIED_LEAD_EVENT`, trimis doar de aici -
pe el optimizeaza campaniile de lead-uri, deci Meta invata doar din cei calificati.
Semnalele de browser (IP, user-agent, ``fbp``/``fbc``) vin din cererea
curenta si nu se salveaza nicaieri.

Un esec Meta nu pierde conversia: ea e deja salvata la noi, cu motivul in
``meta_capi_error``. Webhook-ul retrimis (Gomag reincearca) o retrimite -
doar pe cele care n-au plecat, deci niciodata de doua ori.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlmodel import Session

from ppc_agent.config import ProviderMode
from ppc_agent.errors import ProviderError
from ppc_agent.providers.live.meta import _BASE_URL
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import ClientAccount, ConversionEvent
from ppc_agent_server.settings import get_server_settings
from ppc_agent_server.tracking.models import StandardizedConversion
from ppc_agent_server.tracking.pipeline import find_event

logger = logging.getLogger("ppc_agent_server.tracking.meta_capi")

_TIMEOUT = 10.0

#: Evenimentele standard Meta. Pixelul de pe site trebuie sa foloseasca ACELASI
#: nume, altfel deduplicarea nu se face.
_EVENT_NAMES = {
    "purchase": "Purchase",
    "lead": "Lead",
    "phone_call": "Contact",
    "contact": "Contact",
}

#: Evenimentul lead-urilor calificate, trimis DOAR de server. Un eveniment standard Meta
#: (``SUBMIT_APPLICATION`` in ``promoted_object``), ca ad set-ul sa optimizeze direct pe el,
#: fara conversie personalizata. Pixelul de pe site NU trebuie sa-l trimita niciodata.
QUALIFIED_LEAD_EVENT = "SubmitApplication"
_QUALIFIED_LEAD_TYPES = frozenset({"lead", "phone_call", "contact"})

CapiStatus = Literal["sent", "failed"]


def build_event(event: ConversionEvent, conversion: StandardizedConversion) -> dict[str, Any]:
    """Evenimentul CAPI pentru o conversie salvata.

    Valoarea si moneda vin din randul salvat (dupa calificare: un lead fara
    valoare are deja valoarea proxy a clientului), PII-ul tot de acolo, hash-uit.
    """
    created = event.created_at if event.created_at.tzinfo else event.created_at.replace(tzinfo=UTC)
    user_data: dict[str, Any] = {}
    if event.email_sha256:
        user_data["em"] = [event.email_sha256]
    if event.phone_sha256:
        user_data["ph"] = [event.phone_sha256]
    for field in ("client_ip_address", "client_user_agent", "fbp", "fbc"):
        value = getattr(conversion, field)
        if value:
            user_data[field] = value

    if event.event_type.value == "phone_call":
        action_source = "phone_call"
    elif conversion.client_user_agent and conversion.event_source_url:
        action_source = "website"
    else:
        # Fara user-agent Meta nu accepta un eveniment "website"; o comanda raportata
        # doar de server (webhook Gomag) pleaca ca "other" - pixelul acopera browserul.
        action_source = "other"

    payload: dict[str, Any] = {
        "event_name": _EVENT_NAMES[event.event_type.value],
        "event_time": conversion.event_time or int(created.timestamp()),
        "event_id": event.event_id,
        "action_source": action_source,
        "user_data": user_data,
    }
    if conversion.event_source_url:
        payload["event_source_url"] = conversion.event_source_url
    if event.value is not None:
        payload["custom_data"] = {"value": float(event.value), "currency": event.currency}
    return payload


def send_event(
    payload: dict[str, Any],
    *,
    pixel_id: str,
    access_token: str,
    test_event_code: str = "",
    transport: httpx.BaseTransport | None = None,
) -> None:
    """``POST /{pixel_id}/events`` cu un singur eveniment.

    Raises:
        ProviderError: Meta a refuzat, nu a confirmat primirea, sau nu raspunde.
    """
    if not pixel_id.isdigit():
        raise ProviderError(f"id de pixel Meta invalid: {pixel_id!r}")
    body = {"data": json.dumps([payload])}
    if test_event_code:
        body["test_event_code"] = test_event_code
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            response = client.post(
                f"{_BASE_URL}/{pixel_id}/events",
                data=body,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Meta Conversions API nu raspunde: {type(exc).__name__}") from exc
    try:
        data: object = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ProviderError(f"raspuns Meta CAPI invalid (HTTP {response.status_code})")
    error = data.get("error")
    if response.is_error or error:
        message = error.get("message", "") if isinstance(error, dict) else ""
        raise ProviderError(f"Meta CAPI a refuzat (HTTP {response.status_code}): {message}")
    if data.get("events_received") != 1:
        raise ProviderError(f"Meta CAPI nu a confirmat evenimentul: {data!r}")


def forward_conversion(
    session: Session,
    account: ClientAccount,
    conversion: StandardizedConversion,
    *,
    transport: httpx.BaseTransport | None = None,
) -> CapiStatus | None:
    """Trimite conversia ``conversion.event_id`` la Meta, daca e cazul.

    Returns:
        ``"sent"`` / ``"failed"`` cand s-a incercat; ``None`` cand nu e cazul:
        conversie necalificata, deja trimisa, fara consimtamant de marketing, client
        fara pixel, server in mod mock.
    """
    event = find_event(session, account.id or 0, conversion.event_id)
    if event is None or not event.qualified or event.meta_capi_sent_at is not None:
        return None
    if conversion.marketing_consent is False:  # refuzat in bannerul de cookie-uri
        return None
    if not account.meta_pixel_id:
        return None
    config = _app_config_for(account)
    if config.provider_mode is not ProviderMode.LIVE:
        return None

    log_fields = {
        "client_account_id": account.id,
        "event_id": event.event_id,
        "pixel_id": account.meta_pixel_id,
    }
    try:
        token = config.settings.meta_access_token
        if not token:
            raise ProviderError("contul Meta nu e conectat (lipseste token-ul de acces)")
        payload = build_event(event, conversion)
        payloads = [payload]
        if event.event_type.value in _QUALIFIED_LEAD_TYPES:
            payloads.append({**payload, "event_name": QUALIFIED_LEAD_EVENT})
        # ponytail: un POST per eveniment; la retrimitere, Meta le contopeste pe event_id.
        for item in payloads:
            send_event(
                item,
                pixel_id=account.meta_pixel_id,
                access_token=token,
                test_event_code=get_server_settings().meta_capi_test_event_code,
                transport=transport,
            )
    except ProviderError as exc:
        event.meta_capi_error = str(exc)[:500]
        session.add(event)
        session.commit()
        logger.error(
            "Meta CAPI: conversie netrimisa - %s",
            exc,
            extra={"event": "capi_failed", **log_fields},
        )
        return "failed"

    event.meta_capi_sent_at = datetime.now(tz=UTC)
    event.meta_capi_error = None
    session.add(event)
    session.commit()
    logger.info("Meta CAPI: conversie trimisa", extra={"event": "capi_sent", **log_fields})
    return "sent"
