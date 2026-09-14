"""Teste de fum pentru Faza 0: pachetul se importa si CLI-ul raspunde corect."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ppc_agent import __version__
from ppc_agent.cli import app
from ppc_agent.config import AppConfig, ProviderMode, Settings
from ppc_agent.errors import SetupRequiredError
from ppc_agent.providers.factory import ProviderFactory

runner = CliRunner()

_COMMANDS = (
    "ingest",
    "plan",
    "budget-advice",
    "copy",
    "build-creative",
    "build-storyboard",
    "ingest-tiktok",
    "ingest-swipes",
    "copy-omnichannel",
    "check-fatigue",
    "propose",
    "execute",
    "status",
)


def test_version_is_pinned() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in _COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", _COMMANDS)
def test_each_command_has_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_settings_default_provider_mode_is_mock() -> None:
    assert Settings(_env_file=None).provider_mode is ProviderMode.MOCK


def test_live_factory_raises_setup_required() -> None:
    config = AppConfig(settings=Settings(_env_file=None, provider_mode=ProviderMode.LIVE))
    factory = ProviderFactory(config)
    assert factory.mode is ProviderMode.LIVE
    with pytest.raises(SetupRequiredError):
        factory.gsc().top_queries("https://exemplu.ro/")
    with pytest.raises(SetupRequiredError):
        factory.meta().ad_sets("act_123")
    with pytest.raises(SetupRequiredError):
        factory.meta().campaign_performance("act_123")
    with pytest.raises(SetupRequiredError):
        factory.tiktok_ads().campaign_performance("adv_123")


def test_mock_factory_wires_all_providers() -> None:
    config = AppConfig(settings=Settings(_env_file=None, provider_mode=ProviderMode.MOCK))
    factory = ProviderFactory(config)
    assert factory.crawler() is not None
    assert factory.gsc() is not None
    assert factory.gbp() is not None
    assert factory.keyword_planner() is not None
    assert factory.google_ads() is not None
    assert factory.meta() is not None
    assert factory.tiktok_ads() is not None


def test_live_factory_builds_ad_providers_with_settings_credentials() -> None:
    """Google/Meta/TikTok Ads au clienti live reali - factory-ul trebuie sa le
    transmita credentialele din Settings (fara sa faca niciun apel de retea)."""
    settings = Settings(
        _env_file=None,
        provider_mode=ProviderMode.LIVE,
        google_ads_developer_token="dev-token",
        google_ads_login_customer_id="mcc-1",
        meta_access_token="meta-token",
        tiktok_access_token="tiktok-token",
    )
    factory = ProviderFactory(AppConfig(settings=settings))

    google = factory.google_ads()
    assert google.developer_token == "dev-token"  # type: ignore[attr-defined]
    assert google.login_customer_id == "mcc-1"  # type: ignore[attr-defined]

    meta = factory.meta()
    assert meta.access_token_configured is True  # type: ignore[attr-defined]

    tiktok = factory.tiktok_ads()
    assert tiktok.access_token_configured is True  # type: ignore[attr-defined]
