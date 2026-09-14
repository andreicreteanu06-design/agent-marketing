"""Teste pentru adaptoarele de sursa (Gomag/call tracking/custom_web) si factory."""

from __future__ import annotations

import pytest

from ppc_agent_server.tracking.adapters import (
    CallTrackingAdapter,
    CustomWebAdapter,
    GomagAdapter,
    get_adapter,
)
from ppc_agent_server.tracking.errors import TrackingError

# Forma reala confirmata pe apidocs.gomag.ro (Order -> Read): campurile
# top-level "total"/"currency", contactul in "billing"/"shipping".
_GOMAG_PAYLOAD = {
    "id": 3468,
    "number": "254",
    "total": "801.34",
    "currency": "RON",
    "status": "Finalizata",
    "billing": {
        "firstname": "Ion",
        "lastname": "Popescu",
        "phone": "0712345678",
        "email": "ion.popescu@exemplu.ro",
    },
    "shipping": {
        "firstname": "Ion",
        "lastname": "Popescu",
        "phone": "0712345678",
        "email": "ion.popescu@exemplu.ro",
    },
}


def test_gomag_adapter_maps_total_and_currency() -> None:
    conversion = GomagAdapter().to_standardized(_GOMAG_PAYLOAD, client_id="42")
    assert conversion.event_type == "purchase"
    assert conversion.value == 801.34
    assert conversion.currency == "RON"
    assert conversion.client_id == "42"
    assert conversion.source_platform == "gomag"
    assert conversion.event_id == "gomag_order_3468"


def test_gomag_adapter_extracts_billing_contact() -> None:
    conversion = GomagAdapter().to_standardized(_GOMAG_PAYLOAD, client_id="42")
    assert conversion.customer_email == "ion.popescu@exemplu.ro"
    assert conversion.customer_phone == "0712345678"


def test_gomag_adapter_falls_back_to_shipping_when_billing_missing() -> None:
    payload = {**_GOMAG_PAYLOAD, "billing": {}}
    conversion = GomagAdapter().to_standardized(payload, client_id="42")
    assert conversion.customer_email == "ion.popescu@exemplu.ro"
    assert conversion.customer_phone == "0712345678"


def test_gomag_adapter_uses_number_when_id_missing() -> None:
    payload = {k: v for k, v in _GOMAG_PAYLOAD.items() if k != "id"}
    conversion = GomagAdapter().to_standardized(payload, client_id="42")
    assert conversion.event_id == "gomag_order_254"


def test_gomag_adapter_missing_order_identifier_raises() -> None:
    payload = {k: v for k, v in _GOMAG_PAYLOAD.items() if k not in ("id", "number")}
    with pytest.raises(TrackingError):
        GomagAdapter().to_standardized(payload, client_id="42")


def test_gomag_adapter_passes_through_ad_id_when_present() -> None:
    payload = {**_GOMAG_PAYLOAD, "ad_id": "c_brand"}
    conversion = GomagAdapter().to_standardized(payload, client_id="42")
    assert conversion.ad_id == "c_brand"


def test_gomag_adapter_passes_through_ad_platform_when_present() -> None:
    """Regresie: ad_id fara ad_platform nu ajunge sa creeze AdPerformanceRecord
    (vezi pipeline._get_or_create_ad_record) - ambele trebuie transmise."""
    payload = {**_GOMAG_PAYLOAD, "ad_id": "c_brand", "ad_platform": "google"}
    conversion = GomagAdapter().to_standardized(payload, client_id="42")
    assert conversion.ad_platform == "google"


def test_gomag_adapter_ad_platform_defaults_to_none_when_absent() -> None:
    conversion = GomagAdapter().to_standardized(_GOMAG_PAYLOAD, client_id="42")
    assert conversion.ad_platform is None


_CALL_PAYLOAD = {
    "call_id": "call_789",
    "caller_id": "+40712345678",
    "duration_seconds": 95,
    "call_status": "answered",
}


def test_call_tracking_adapter_maps_phone_and_duration() -> None:
    conversion = CallTrackingAdapter().to_standardized(_CALL_PAYLOAD, client_id="7")
    assert conversion.event_type == "phone_call"
    assert conversion.customer_phone == "+40712345678"
    assert conversion.call_duration_seconds == 95
    assert conversion.lead_status == "answered"
    assert conversion.value is None
    assert conversion.event_id == "call_call_789"


def test_call_tracking_adapter_accepts_alternate_field_names() -> None:
    payload = {"id": "abc", "from_number": "0723456789", "duration": "42"}
    conversion = CallTrackingAdapter().to_standardized(payload, client_id="7")
    assert conversion.customer_phone == "0723456789"
    assert conversion.call_duration_seconds == 42


def test_call_tracking_adapter_missing_call_id_raises() -> None:
    with pytest.raises(TrackingError):
        CallTrackingAdapter().to_standardized({"caller_id": "x"}, client_id="7")


def test_call_tracking_adapter_passes_through_ad_id_and_platform_when_present() -> None:
    payload = {**_CALL_PAYLOAD, "ad_id": "tt_infeed", "ad_platform": "tiktok"}
    conversion = CallTrackingAdapter().to_standardized(payload, client_id="7")
    assert conversion.ad_id == "tt_infeed"
    assert conversion.ad_platform == "tiktok"


def test_custom_web_adapter_validates_and_stamps_client_id() -> None:
    payload = {
        "event_id": "e1",
        "event_type": "lead",
        "client_id": "someone-elses-id",
        "source_platform": "custom_web",
    }
    conversion = CustomWebAdapter().to_standardized(payload, client_id="99")
    assert conversion.client_id == "99"  # autoritar, suprascrie payload-ul


def test_custom_web_adapter_invalid_payload_raises() -> None:
    with pytest.raises(TrackingError):
        CustomWebAdapter().to_standardized({"event_type": "not_a_real_type"}, client_id="1")


def test_get_adapter_factory_dispatches_by_source() -> None:
    assert isinstance(get_adapter("gomag"), GomagAdapter)
    assert isinstance(get_adapter("call_tracker"), CallTrackingAdapter)
    assert isinstance(get_adapter("custom_web"), CustomWebAdapter)


def test_get_adapter_unknown_source_raises() -> None:
    with pytest.raises(TrackingError):
        get_adapter("shopify")
