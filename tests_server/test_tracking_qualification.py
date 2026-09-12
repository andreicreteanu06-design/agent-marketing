"""Teste pentru ConversionQualifier: valori proxy + poarta de durata a apelului."""

from __future__ import annotations

from ppc_agent_server.tracking.models import StandardizedConversion
from ppc_agent_server.tracking.qualification import ConversionQualifier

_QUALIFIER = ConversionQualifier(default_lead_value=300.0)


def _conversion(**overrides: object) -> StandardizedConversion:
    defaults: dict[str, object] = dict(
        event_id="e1", client_id="1", source_platform="custom_web"
    )
    defaults.update(overrides)
    return StandardizedConversion(**defaults)  # type: ignore[arg-type]


def test_purchase_with_value_is_qualified_and_value_unchanged() -> None:
    result = _QUALIFIER.qualify(_conversion(event_type="purchase", value=199.99))
    assert result.qualified
    assert result.conversion.value == 199.99


def test_lead_without_value_gets_proxy_value() -> None:
    result = _QUALIFIER.qualify(_conversion(event_type="lead", value=None))
    assert result.qualified
    assert result.conversion.value == 300.0


def test_lead_with_explicit_value_keeps_it_not_proxy() -> None:
    result = _QUALIFIER.qualify(_conversion(event_type="lead", value=50.0))
    assert result.conversion.value == 50.0


def test_contact_without_value_does_not_get_proxy_value() -> None:
    """Doar 'lead'/'phone_call' primesc proxy - 'contact' nu e mentionat in cerere."""
    result = _QUALIFIER.qualify(_conversion(event_type="contact", value=None))
    assert result.qualified
    assert result.conversion.value is None


def test_phone_call_over_minimum_duration_is_qualified_with_proxy_value() -> None:
    result = _QUALIFIER.qualify(
        _conversion(event_type="phone_call", value=None, call_duration_seconds=90)
    )
    assert result.qualified
    assert result.conversion.value == 300.0
    assert result.reason is None


def test_phone_call_exactly_at_minimum_duration_is_qualified() -> None:
    result = _QUALIFIER.qualify(
        _conversion(event_type="phone_call", call_duration_seconds=60)
    )
    assert result.qualified


def test_phone_call_under_minimum_duration_is_unqualified() -> None:
    result = _QUALIFIER.qualify(
        _conversion(event_type="phone_call", call_duration_seconds=45)
    )
    assert not result.qualified
    assert result.reason is not None
    assert "45s" in result.reason


def test_phone_call_without_known_duration_is_unqualified() -> None:
    """Fara durata cunoscuta nu putem verifica pragul - tratat conservator, ca esec."""
    result = _QUALIFIER.qualify(
        _conversion(event_type="phone_call", call_duration_seconds=None)
    )
    assert not result.qualified
    assert "necunoscuta" in (result.reason or "")


def test_unqualified_phone_call_still_gets_proxy_value_for_audit() -> None:
    """Valoarea proxy tot se aplica - descalificarea e despre CONTORIZARE, nu valoare."""
    result = _QUALIFIER.qualify(
        _conversion(event_type="phone_call", call_duration_seconds=10)
    )
    assert not result.qualified
    assert result.conversion.value == 300.0
