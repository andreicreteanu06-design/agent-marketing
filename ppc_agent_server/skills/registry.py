"""Registrul de abilitati (skills) ale agentilor, pregatit pentru MCP.

Uneltele cu retea nu mai stau in modulele agentilor: fiecare e un
:class:`BaseAgentSkill` - nume, descriere, ``execute`` asincron - iar agentii le
cer dupa nume (``await registry.execute("web_search", query=...)``). Numele si
descrierea sunt exact ce cere un ``tools/list`` in Model Context Protocol, deci
serverul MCP (``ppc_agent_server/mcp``) le poate expune fara sa stie ce fac.

Ideea vine din sickn33/agentic-awesome-skills (abilitati descoperite dupa nume,
nu importate); niciun rand copiat. Registrul implicit e in ``skills/__init__.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import Any, ClassVar


class BaseAgentSkill(ABC):
    """O abilitate: fara stare intre apeluri, tot contextul vine prin ``kwargs``."""

    name: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Ruleaza abilitatea; argumentele gresite ridica ``ValueError``."""


class SkillRegistry:
    """Abilitatile, dupa nume."""

    def __init__(self, skills: Iterable[BaseAgentSkill] = ()) -> None:
        self._skills: dict[str, BaseAgentSkill] = {}
        for skill in skills:
            self.register(skill)

    def register(self, skill: BaseAgentSkill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"abilitatea «{skill.name}» e deja înregistrată")
        self._skills[skill.name] = skill

    def __iter__(self) -> Iterator[BaseAgentSkill]:
        return iter(self._skills.values())

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """Ruleaza abilitatea ``name``.

        Raises:
            LookupError: nu exista o abilitate cu numele asta.
        """
        skill = self._skills.get(name)
        if skill is None:
            raise LookupError(f"nu există abilitatea «{name}»")
        return await skill.execute(**kwargs)
