"""Abilitatile agentilor, dupa nume (``registry.py``); ``skill_registry`` e registrul implicit."""

from __future__ import annotations

from ppc_agent_server.skills.registry import BaseAgentSkill, SkillRegistry
from ppc_agent_server.skills.web_search import WebSearchSkill

skill_registry = SkillRegistry([WebSearchSkill()])

__all__ = ["BaseAgentSkill", "SkillRegistry", "WebSearchSkill", "skill_registry"]
