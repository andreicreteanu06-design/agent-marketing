"""Conversiile calificate, trimise de pe server si la Google Ads, TikTok si ChatGPT.

Acelasi rost ca ``meta_capi.py``: algoritmul fiecarei platforme alege cui arata
reclama dupa conversiile pe care le primeste, iar pixelii din browser pierd o parte
din ele (blocare, iOS, consimtamant). Trimise de aici, ajung toate.

Cum se potrivesc cu clickul pe reclama:

- **Google Ads** - conversie importata (``uploadClickConversions``) cu ``gclid`` /
  ``gbraid`` / ``wbraid`` si, pentru Enhanced Conversions, emailul si telefonul
  hash-uite. Actiunea de conversie a clientului trebuie sa fie de tip "import din
  click-uri" (``ClientAccount.google_ads_conversion_action_id``).
- **TikTok** - Events API, cu ``ttclid``, cookie-ul ``_ttp``, emailul si telefonul
  hash-uite. Pixelul de pe site trebuie sa trimita acelasi ``event_id`` (deduplicare):
  ``ttq.track('CompletePayment', {...}, {event_id: 'gomag_order_1001'})``.
- **ChatGPT** - Conversions API din OpenAI Ads, cu ``oppref`` si aceleasi hash-uri ca
  la Meta. Cheia lui e separata de cea de reclame (``chatgpt_conversions_key_enc``).

Google si TikTok cer telefonul cu ``+`` in fata (E.164), Google si emailul de Gmail
fara puncte: hash-urile lor se calculeaza din datele in clar, cat conversia e in
memorie - in baza de date raman doar cele in forma Meta.

Ce nu pleaca: conversiile necalificate, cele deja trimise (un webhook retrimis
reincearca doar ce a esuat), cele cu ``marketing_consent`` refuzat si orice in mod
``mock``. Un esec nu pierde conversia: motivul ramane pe rand (``*_error``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
from sqlmodel import Session

from ppc_agent.config import ProviderMode
from ppc_agent.errors import PpcAgentError, ProviderError
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent.providers.live.google_ads import LiveGoogleAdsProvider
from ppc_agent.providers.live.tiktok import LiveTikTokAdsProvider
from ppc_agent_server.jobs.tasks import _app_config_for
from ppc_agent_server.models import ClientAccount, ConversionEvent
from ppc_agent_server.security import decrypt_secret
from ppc_agent_server.settings import get_server_settings
from ppc_agent_server.tracking.models import (
    StandardizedConversion,
    hash_email_google,
    hash_phone_e164,
    hash_pii,
)
from ppc_agent_server.tracking.pipeline import find_event

logger = logging.getLogger("ppc_agent_server.tracking.platform_conversions")

Status = Literal["sent", "failed"]

#: Evenimentele standard TikTok. Pixelul de pe site trebuie sa foloseasca acelasi nume.
_TIKTOK_EVENTS = {
    "purchase": "CompletePayment",
    "lead": "SubmitForm",
    "phone_call": "Contact",
    "contact": "Contact",
}
#: OpenAI Ads are doar comenzi si lead-uri printre evenimentele lui standard.
_CHATGPT_EVENTS = {"purchase": "order_created", "lead": "lead_created"}
#: Google: actiunea de conversie importata e una singura - vanzari sau lead-uri.
_GOOGLE_EVENT_TYPES = frozenset({"purchase", "lead"})

CHATGPT_EVENTS_URL = "https://bzr.openai.com/v1/events"
#: Partenerii trimit acelasi identificator pe fiecare cerere (cerinta OpenAI).
_INTEGRATION_SOURCE = "ac_media"
_TIMEOUT = 10.0


def _event_time(event: ConversionEvent, conversion: StandardizedConversion) -> datetime:
    if conversion.event_time:
        return datetime.fromtimestamp(conversion.event_time, tz=UTC)
    created = event.created_at
    return created if created.tzinfo else created.replace(tzinfo=UTC)


# --- Google Ads ---------------------------------------------------------------------


def build_google_conversion(
    event: ConversionEvent,
    conversion: StandardizedConversion,
    *,
    customer_id: str,
    conversion_action_id: str,
) -> dict[str, Any] | None:
    """``ClickConversion`` pentru ``uploadClickConversions``; ``None`` cand nu are cu ce
    se potrivi (niciun id de click, niciun email sau telefon)."""
    identifiers: list[dict[str, str]] = []
    if email := hash_email_google(conversion.customer_email):
        identifiers.append({"hashedEmail": email})
    if phone := hash_phone_e164(conversion.customer_phone):
        identifiers.append({"hashedPhoneNumber": phone})
    # Google accepta un singur id de click pe conversie: gclid, altfel cele de pe iOS.
    click = next(
        (
            (name, value)
            for name in ("gclid", "gbraid", "wbraid")
            if (value := getattr(conversion, name))
        ),
        None,
    )
    if click is None and not identifiers:
        return None
    payload: dict[str, Any] = {
        "conversionAction": f"customers/{customer_id}/conversionActions/{conversion_action_id}",
        "conversionDateTime": _event_time(event, conversion).strftime("%Y-%m-%d %H:%M:%S+00:00"),
        "orderId": event.event_id,
    }
    if click is not None:
        payload[click[0]] = click[1]
    if identifiers:
        payload["userIdentifiers"] = identifiers
    if event.value is not None:
        payload["conversionValue"] = float(event.value)
        payload["currencyCode"] = event.currency
    if conversion.marketing_consent:
        payload["consent"] = {"adUserData": "GRANTED"}
    return payload


def _send_google(
    account: ClientAccount,
    event: ConversionEvent,
    conversion: StandardizedConversion,
    factory: ProviderFactory,
) -> bool:
    if event.event_type.value not in _GOOGLE_EVENT_TYPES:
        return False
    if not account.google_ads_conversion_action_id or not factory.configured("google_ads"):
        return False
    customer_id = factory.settings.google_ads_customer_id.replace("-", "")
    payload = build_google_conversion(
        event,
        conversion,
        customer_id=customer_id,
        conversion_action_id=account.google_ads_conversion_action_id,
    )
    if payload is None:
        return False
    reader = factory.google_ads()
    assert isinstance(reader, LiveGoogleAdsProvider)
    reader.upload_click_conversion(customer_id, payload)
    return True


# --- TikTok -------------------------------------------------------------------------


def build_tiktok_event(
    event: ConversionEvent,
    conversion: StandardizedConversion,
    *,
    pixel_code: str,
    test_event_code: str = "",
) -> dict[str, Any]:
    """Corpul ``/event/track/`` (Events API 2.0) pentru o conversie salvata."""
    user: dict[str, str] = {}
    for key, value in (
        ("ttclid", conversion.ttclid),
        ("ttp", conversion.ttp),
        ("email", hash_pii(conversion.customer_email)),
        ("phone", hash_phone_e164(conversion.customer_phone)),
        ("ip", conversion.client_ip_address),
        ("user_agent", conversion.client_user_agent),
    ):
        if value:
            user[key] = value
    data: dict[str, Any] = {
        "event": _TIKTOK_EVENTS[event.event_type.value],
        "event_time": int(_event_time(event, conversion).timestamp()),
        "event_id": event.event_id,
        "user": user,
    }
    if event.value is not None:
        data["properties"] = {"value": float(event.value), "currency": event.currency}
    if conversion.event_source_url:
        data["page"] = {"url": conversion.event_source_url}
    payload: dict[str, Any] = {
        "event_source": "web",
        "event_source_id": pixel_code,
        "data": [data],
    }
    if test_event_code:
        payload["test_event_code"] = test_event_code
    return payload


def _send_tiktok(
    account: ClientAccount,
    event: ConversionEvent,
    conversion: StandardizedConversion,
    factory: ProviderFactory,
) -> bool:
    if not account.tiktok_pixel_code or not factory.settings.tiktok_access_token:
        return False
    reader = factory.tiktok_ads()
    assert isinstance(reader, LiveTikTokAdsProvider)
    reader.track_event(
        build_tiktok_event(
            event,
            conversion,
            pixel_code=account.tiktok_pixel_code,
            test_event_code=get_server_settings().tiktok_events_test_code,
        )
    )
    return True


# --- ChatGPT (OpenAI Ads) -----------------------------------------------------------


def build_chatgpt_event(
    event: ConversionEvent, conversion: StandardizedConversion, *, fallback_url: str
) -> dict[str, Any] | None:
    """Un eveniment pentru Conversions API din OpenAI Ads; ``None`` pentru tipurile pe
    care OpenAI nu le are (apeluri, contact)."""
    event_type = _CHATGPT_EVENTS.get(event.event_type.value)
    if event_type is None:
        return None
    user: dict[str, Any] = {}
    # Aceeasi normalizare ca la Meta (email cu litere mici, telefon doar cifre), deci
    # hash-urile salvate se potrivesc.
    if event.email_sha256:
        user["emails_sha256"] = [event.email_sha256]
    if event.phone_sha256:
        user["phone_numbers_sha256"] = [event.phone_sha256]
    if conversion.client_ip_address:
        user["ip_address"] = conversion.client_ip_address
    if conversion.client_user_agent:
        user["user_agent"] = conversion.client_user_agent
    payload: dict[str, Any] = {
        "id": event.event_id,
        "type": event_type,
        "timestamp_ms": int(_event_time(event, conversion).timestamp() * 1000),
        # Obligatoriu la evenimentele web; o comanda raportata doar de server a avut loc
        # tot pe site-ul clientului.
        "source_url": conversion.event_source_url or fallback_url,
        "user": user,
    }
    if conversion.oppref:
        payload["oppref"] = conversion.oppref
    if event_type == "order_created":
        data: dict[str, Any] = {"type": "contents"}
        if event.value is not None:
            # Suma in subunitatea monedei (bani), ca intreg.
            data["amount"] = int((event.value * Decimal(100)).to_integral_value())
            data["currency"] = event.currency
        payload["data"] = data
    else:
        payload["data"] = {"type": "customer_action"}
    return payload


def send_chatgpt_events(
    events: list[dict[str, Any]],
    *,
    pixel_id: str,
    api_key: str,
    validate_only: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """``POST bzr.openai.com/v1/events?pid=...``. OpenAI respinge tot lotul daca un
    eveniment e gresit - aici lotul e de un eveniment.

    Raises:
        ProviderError: OpenAI a refuzat evenimentul sau nu raspunde.
    """
    body: dict[str, Any] = {
        "validate_only": validate_only,
        "integration_source": _INTEGRATION_SOURCE,
        "events": events,
    }
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            response = client.post(
                CHATGPT_EVENTS_URL,
                params={"pid": pixel_id},
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Conversions API OpenAI nu raspunde: {type(exc).__name__}") from exc
    if response.is_error:
        try:
            error = response.json().get("error")
        except ValueError:
            error = None
        message = error.get("message", "") if isinstance(error, dict) else ""
        raise ProviderError(
            f"Conversions API OpenAI a refuzat (HTTP {response.status_code}): {message}"
        )


def _send_chatgpt(
    account: ClientAccount,
    event: ConversionEvent,
    conversion: StandardizedConversion,
    factory: ProviderFactory,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    if not account.chatgpt_pixel_id or not account.chatgpt_conversions_key_enc:
        return False
    payload = build_chatgpt_event(
        event, conversion, fallback_url=account.target_domain or "https://localhost"
    )
    if payload is None:
        return False
    send_chatgpt_events(
        [payload],
        pixel_id=account.chatgpt_pixel_id,
        api_key=decrypt_secret(account.chatgpt_conversions_key_enc),
        validate_only=get_server_settings().chatgpt_conversions_validate_only,
        transport=transport,
    )
    return True


# --- toate platformele --------------------------------------------------------------

_Sender = Callable[[ClientAccount, ConversionEvent, StandardizedConversion, ProviderFactory], bool]

#: (platforma, coloana de stare de pe ``ConversionEvent``, trimiterea).
_PLATFORMS: tuple[tuple[str, str, _Sender], ...] = (
    ("google_ads", "google_ads", _send_google),
    ("tiktok", "tiktok_events", _send_tiktok),
    ("chatgpt", "chatgpt_events", _send_chatgpt),
)


def forward_to_platforms(
    session: Session,
    account: ClientAccount,
    conversion: StandardizedConversion,
    *,
    senders: tuple[tuple[str, str, _Sender], ...] = _PLATFORMS,
) -> dict[str, Status]:
    """Trimite conversia ``conversion.event_id`` la fiecare platforma configurata.

    Returns:
        ``{platforma: "sent" | "failed"}`` doar pentru platformele unde s-a incercat.
    """
    event = find_event(session, account.id or 0, conversion.event_id)
    if event is None or not event.qualified or conversion.marketing_consent is False:
        return {}
    config = _app_config_for(account)
    if config.provider_mode is not ProviderMode.LIVE:
        return {}
    factory = ProviderFactory(config)
    outcome: dict[str, Status] = {}
    for platform, column, send in senders:
        if getattr(event, f"{column}_sent_at") is not None:
            continue
        log_fields = {"client_account_id": account.id, "event_id": event.event_id}
        try:
            if not send(account, event, conversion, factory):
                continue
        except PpcAgentError as exc:
            setattr(event, f"{column}_error", str(exc)[:500])
            outcome[platform] = "failed"
            logger.error(
                "%s: conversie netrimisa - %s",
                platform,
                exc,
                extra={"event": f"{platform}_conversion_failed", **log_fields},
            )
            continue
        setattr(event, f"{column}_sent_at", datetime.now(tz=UTC))
        setattr(event, f"{column}_error", None)
        outcome[platform] = "sent"
        logger.info(
            "%s: conversie trimisa",
            platform,
            extra={"event": f"{platform}_conversion_sent", **log_fields},
        )
    if outcome:
        session.add(event)
        session.commit()
    return outcome
