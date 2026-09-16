"""Teste pentru SeoGeoSettings - in special aliasul jwt_secret_key (fara prefix)."""

from __future__ import annotations

import pytest

from seo_geo_agent.settings import ProviderMode, SeoGeoSettings, get_seo_geo_settings


def test_jwt_secret_key_reads_unprefixed_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """jwt_secret_key trebuie sa citeasca JWT_SECRET_KEY, NU SEOGEO_JWT_SECRET_KEY -
    e secretul partajat cu ppc_agent_server (vezi docstring-ul modulului)."""
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-comun")
    monkeypatch.delenv("SEOGEO_JWT_SECRET_KEY", raising=False)
    settings = SeoGeoSettings()
    assert settings.jwt_secret_key == "secret-comun"


def test_unprefixed_jwt_secret_key_wins_over_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ambele variabile setate deodata - varianta fara prefix trebuie sa castige,
    nu doar sa fie singura prezenta (vezi testul de mai sus, care nu ar prinde
    un bug in care aliasul ar cadea inapoi pe numele prefixat)."""
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-comun")
    monkeypatch.setenv("SEOGEO_JWT_SECRET_KEY", "nu-ar-trebui-citit")
    settings = SeoGeoSettings()
    assert settings.jwt_secret_key == "secret-comun"


def test_llm_settings_use_seogeo_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEOGEO_LLM_MODEL", "ollama/qwen2.5")
    monkeypatch.setenv("SEOGEO_PROVIDER_MODE", "live")
    settings = SeoGeoSettings()
    assert settings.llm_model == "ollama/qwen2.5"
    assert settings.provider_mode is ProviderMode.LIVE


def test_default_provider_mode_is_mock() -> None:
    assert SeoGeoSettings().provider_mode is ProviderMode.MOCK


def test_get_seo_geo_settings_is_cached() -> None:
    assert get_seo_geo_settings() is get_seo_geo_settings()
