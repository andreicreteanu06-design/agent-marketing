"""Registrul de abilitati: agentii cer uneltele dupa nume, ca intr-un ``tools/list`` MCP."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ppc_agent_server.skills import BaseAgentSkill, SkillRegistry, WebSearchSkill, skill_registry


class _Echo(BaseAgentSkill):
    name = "echo"
    description = "Întoarce ce primește."

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs


def test_a_skill_runs_by_name_with_its_arguments() -> None:
    registry = SkillRegistry([_Echo()])

    assert asyncio.run(registry.execute("echo", query="service auto")) == {"query": "service auto"}


def test_names_are_unique_and_unknown_skills_are_refused() -> None:
    registry = SkillRegistry([_Echo()])

    with pytest.raises(ValueError, match="deja înregistrată"):
        registry.register(_Echo())
    with pytest.raises(LookupError, match="nu există abilitatea «pagespeed»"):
        asyncio.run(registry.execute("pagespeed", url="https://exemplu.ro"))


def test_the_default_registry_describes_its_tools_like_mcp() -> None:
    assert [(skill.name, skill.description.split(" (")[0]) for skill in skill_registry] == [
        ("web_search", "Caută pe web")
    ]


@pytest.mark.parametrize("kwargs", [{}, {"query": "   "}, {"query": 42}])
def test_web_search_refuses_a_missing_query_before_any_request(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="query"):
        asyncio.run(WebSearchSkill().execute(**kwargs))
