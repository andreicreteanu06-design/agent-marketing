"""Teste pentru StandardizedConversion si hash_pii (normalizare + SHA-256)."""

from __future__ import annotations

import hashlib

from ppc_agent_server.tracking.models import StandardizedConversion, hash_pii


def test_standardized_conversion_defaults() -> None:
    conversion = StandardizedConversion(
        event_id="e1", client_id="1", source_platform="custom_web"
    )
    assert conversion.event_type == "purchase"
    assert conversion.currency == "RON"
    assert conversion.value is None
    assert conversion.ad_id is None
    assert conversion.ad_platform is None


def test_hash_pii_returns_none_for_missing_value() -> None:
    assert hash_pii(None) is None
    assert hash_pii("") is None


def test_hash_pii_email_is_lowercased_and_trimmed_before_hashing() -> None:
    expected = hashlib.sha256(b"test@example.com").hexdigest()
    assert hash_pii("  Test@Example.com  ") == expected
    assert hash_pii("test@example.com") == expected


def test_hash_pii_phone_keeps_only_digits() -> None:
    expected = hashlib.sha256(b"40712345678").hexdigest()
    assert hash_pii("+40 712 345 678", is_phone=True) == expected
    assert hash_pii("0040712345678", is_phone=True) != expected  # cifre diferite


def test_hash_pii_is_deterministic() -> None:
    first = hash_pii("Cineva@Exemplu.RO")
    second = hash_pii("cineva@exemplu.ro")
    assert first == second
    assert len(first or "") == 64  # hex SHA-256
