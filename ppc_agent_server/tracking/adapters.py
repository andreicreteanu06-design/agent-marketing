"""Adaptoare de sursa: transforma payload-uri terte in ``StandardizedConversion``.

Factory simplu (``get_adapter``) ales dupa ``source_platform`` - fiecare
adaptor stie doar sa citeasca FORMA specifica sursei lui, nu si cum se
califica sau se persista conversia (asta traieste in ``qualification.py`` /
``pipeline.py``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from ppc_agent_server.tracking.errors import TrackingError
from ppc_agent_server.tracking.models import StandardizedConversion


class BaseSourceAdapter(ABC):
    """Interfata unui adaptor: payload brut -> :class:`StandardizedConversion`."""

    @abstractmethod
    def to_standardized(
        self, raw_payload: dict[str, Any], *, client_id: str
    ) -> StandardizedConversion:
        """Transforma ``raw_payload`` in forma unificata.

        Args:
            raw_payload: Corpul cererii, asa cum a fost trimis de sursa.
            client_id: Contul-client autoritar (validat deja fata de agentia
                autentificata, in ``routers/tracking.py``) - NU se citeste din
                ``raw_payload`` (o sursa terta nu are niciun concept despre
                ID-ul nostru intern de client).

        Raises:
            TrackingError: Payload-ul nu contine campurile minime asteptate.
        """


#: ID-urile de click si cookie-urile platformelor, cand sursa le trimite (un camp
#: personalizat al comenzii, un call tracker care pastreaza ``gclid``-ul apelantului).
_CLICK_IDS = ("gclid", "gbraid", "wbraid", "ttclid", "ttp", "oppref", "fbc", "fbp")


def _click_ids(raw_payload: dict[str, Any]) -> dict[str, str]:
    return {key: str(raw_payload[key]) for key in _CLICK_IDS if raw_payload.get(key)}


def _parse_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise TrackingError(f"valoare numerica invalida: {raw!r}") from exc


def _parse_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError) as exc:
        raise TrackingError(f"valoare intreaga invalida: {raw!r}") from exc


class GomagAdapter(BaseSourceAdapter):
    """Adaptor pentru payload-ul de comanda Gomag (schema reala, apidocs.gomag.ro).

    Mapeaza ``total``/``currency`` -> ``value``/``currency``, contactul din
    ``billing`` (cu fallback pe ``shipping`` daca ``billing`` lipseste) ->
    ``customer_email``/``customer_phone``, ``id`` (sau ``number``) ->
    ``event_id``. Intotdeauna ``event_type="purchase"``. ``ad_id``/``ad_platform``
    nu exista in schema reala Gomag - sunt extensii ale noastre (vezi
    ``tracking/models.py``), transmise mai departe DOAR daca sunt prezente in
    payload; fara ambele, conversia se califica dar nu se leaga de niciun anunt
    (``AdPerformanceRecord`` nu se creeaza - vezi ``pipeline._get_or_create_ad_record``).
    """

    def to_standardized(
        self, raw_payload: dict[str, Any], *, client_id: str
    ) -> StandardizedConversion:
        order_id = raw_payload.get("id") or raw_payload.get("number")
        if not order_id:
            raise TrackingError("payload Gomag fara 'id' sau 'number'")

        billing = raw_payload.get("billing") or {}
        shipping = raw_payload.get("shipping") or {}

        try:
            return StandardizedConversion(
                event_id=f"gomag_order_{order_id}",
                event_type="purchase",
                value=_parse_float(raw_payload.get("total")),
                currency=str(raw_payload.get("currency") or "RON"),
                customer_email=billing.get("email") or shipping.get("email"),
                customer_phone=billing.get("phone") or shipping.get("phone"),
                client_id=client_id,
                source_platform="gomag",
                ad_id=raw_payload.get("ad_id"),
                ad_platform=raw_payload.get("ad_platform"),
            ).model_copy(update=_click_ids(raw_payload))
        except ValidationError as exc:
            raise TrackingError(f"payload Gomag invalid: {exc}") from exc


class CallTrackingAdapter(BaseSourceAdapter):
    """Adaptor generic pentru un webhook de call tracking (VoIP).

    Nu exista un format 'standard' unic intre furnizorii de call tracking -
    foloseste denumiri de campuri comune majoritatii lor (``call_id``/
    ``caller_id``/``duration_seconds``/``call_status``); ajusteaza cheile de
    mapare la furnizorul real folosit. Intotdeauna ``event_type="phone_call"``;
    valoarea ramane ``None`` aici - proxy-ul se aplica in
    ``ConversionQualifier``, nu in adaptor. ``ad_id``/``ad_platform`` transmise
    mai departe DOAR daca sunt prezente in payload (vezi nota din ``GomagAdapter``).
    """

    def to_standardized(
        self, raw_payload: dict[str, Any], *, client_id: str
    ) -> StandardizedConversion:
        call_id = raw_payload.get("call_id") or raw_payload.get("id")
        if not call_id:
            raise TrackingError("payload call tracking fara 'call_id'/'id'")

        try:
            return StandardizedConversion(
                event_id=f"call_{call_id}",
                event_type="phone_call",
                customer_phone=raw_payload.get("caller_id") or raw_payload.get("from_number"),
                client_id=client_id,
                source_platform="call_tracker",
                lead_status=raw_payload.get("call_status"),
                call_duration_seconds=_parse_int(
                    raw_payload.get("duration_seconds") or raw_payload.get("duration")
                ),
                ad_id=raw_payload.get("ad_id"),
                ad_platform=raw_payload.get("ad_platform"),
            ).model_copy(update=_click_ids(raw_payload))
        except ValidationError as exc:
            raise TrackingError(f"payload call tracking invalid: {exc}") from exc


class CustomWebAdapter(BaseSourceAdapter):
    """Payload deja in forma ``StandardizedConversion`` (backend propriu al clientului).

    Nu transforma nimic - doar valideaza si stampeaza ``client_id`` autoritar
    (suprascrie orice ``client_id`` ar veni in payload, din acelasi motiv ca
    la celelalte adaptoare: sursa poate minti, ruta autentificata nu).
    """

    def to_standardized(
        self, raw_payload: dict[str, Any], *, client_id: str
    ) -> StandardizedConversion:
        try:
            return StandardizedConversion.model_validate({**raw_payload, "client_id": client_id})
        except ValidationError as exc:
            raise TrackingError(f"payload custom_web invalid: {exc}") from exc


_ADAPTERS: dict[str, BaseSourceAdapter] = {
    "gomag": GomagAdapter(),
    "call_tracker": CallTrackingAdapter(),
    "custom_web": CustomWebAdapter(),
}


def get_adapter(source_platform: str) -> BaseSourceAdapter:
    """Factory: alege adaptorul potrivit dupa ``source_platform``.

    Raises:
        TrackingError: ``source_platform`` nu e una dintre sursele suportate.
    """
    try:
        return _ADAPTERS[source_platform]
    except KeyError:
        raise TrackingError(
            f"sursa '{source_platform}' nu e suportata - disponibile: "
            f"{', '.join(sorted(_ADAPTERS))}"
        ) from None
