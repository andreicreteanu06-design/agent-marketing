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

_COMMANDS = ("ingest", "plan", "propose", "execute", "status")


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


def test_mock_factory_not_yet_implemented() -> None:
    config = AppConfig(settings=Settings(_env_file=None, provider_mode=ProviderMode.MOCK))
    factory = ProviderFactory(config)
    with pytest.raises(NotImplementedError):
        factory.crawler()
