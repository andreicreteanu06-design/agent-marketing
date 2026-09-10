"""Politica ``robots.txt`` pentru crawler, bazata pe biblioteca standard."""

from __future__ import annotations

from urllib.robotparser import RobotFileParser


class RobotsPolicy:
    """Invelis subtire peste :class:`urllib.robotparser.RobotFileParser`."""

    def __init__(self, robots_txt: str | None, user_agent: str) -> None:
        """Construieste politica dintr-un continut ``robots.txt``.

        Args:
            robots_txt: Continutul fisierului, sau ``None`` pentru "permite tot".
            user_agent: Agentul pentru care se evalueaza regulile.
        """
        self._user_agent = user_agent
        self._parser = RobotFileParser()
        lines = [] if robots_txt is None else robots_txt.splitlines()
        self._parser.parse(lines)

    def can_fetch(self, url: str) -> bool:
        """Adevarat daca ``url`` poate fi accesat de agentul configurat."""
        return self._parser.can_fetch(self._user_agent, url)
