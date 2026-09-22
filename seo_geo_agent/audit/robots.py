"""robots.txt: ce are voie crawler-ul si ce sitemap-uri declara site-ul.

``every-app/open-seo`` foloseste pachetul npm ``robots-parser``; in Python,
echivalentul din biblioteca standard (``urllib.robotparser``) NU intelege
wildcard-urile ``*`` si ``$`` din caile Allow/Disallow - adica exact regulile
pe care le scriu site-urile reale (``Disallow: /*?filter=``). Asa ca parsam noi,
dupa RFC 9309 si dupa comportamentul documentat de Google:

- grupurile se aleg dupa cel mai SPECIFIC user-agent care se potriveste (token
  exact, insensibil la litere mari/mici), cu ``*`` ca ultima varianta;
- in cadrul grupului castiga regula cu cel mai lung tipar potrivit, iar la
  egalitate castiga ``Allow`` (regula lui Google);
- un ``Disallow:`` gol inseamna "permite tot".

Verificarea pe user-agent nominal nu e un moft: de ea depinde verificarea GEO
``ai-crawler-blocked`` (GPTBot, ClaudeBot, PerplexityBot, Google-Extended pot fi
blocate individual, fara ca ``*`` sa fie atins) - vezi ``geo_reporters.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

#: Crawler-ele care alimenteaza raspunsurile generative, pe platforma.
AI_CRAWLERS: dict[str, str] = {
    "GPTBot": "ChatGPT (OpenAI)",
    "OAI-SearchBot": "ChatGPT Search (OpenAI)",
    "ClaudeBot": "Claude (Anthropic)",
    "PerplexityBot": "Perplexity",
    "Google-Extended": "Google AI Overviews / Gemini",
    "Applebot-Extended": "Apple Intelligence",
}


@dataclass(frozen=True, slots=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def specificity(self) -> int:
        """Lungimea tiparului - criteriul de departajare intre reguli (ca la Google)."""
        return len(self.pattern)


def _compile_path_pattern(path: str) -> re.Pattern[str]:
    """Traduce un tipar de cale din robots.txt in regex.

    ``*`` = orice secventa, ``$`` la final = ancora de sfarsit. Restul
    caracterelor sunt literale (deci escapate).
    """
    anchored_end = path.endswith("$")
    body = path[:-1] if anchored_end else path
    parts = [re.escape(segment) for segment in body.split("*")]
    return re.compile("^" + ".*".join(parts) + ("$" if anchored_end else ""))


@dataclass(slots=True)
class RobotsTxt:
    """Rezultatul parsarii unui robots.txt. ``None`` la fetch => totul e permis."""

    groups: dict[str, list[_Rule]] = field(default_factory=dict)
    sitemaps: list[str] = field(default_factory=list)
    fetched: bool = False

    def _group_for(self, user_agent: str) -> list[_Rule] | None:
        """Grupul care se aplica lui ``user_agent``: cel mai specific, apoi ``*``."""
        target = user_agent.lower()
        best: tuple[int, list[_Rule]] | None = None
        for agent, rules in self.groups.items():
            if agent == "*":
                continue
            if agent in target and (best is None or len(agent) > best[0]):
                best = (len(agent), rules)
        if best is not None:
            return best[1]
        return self.groups.get("*")

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Spune daca ``user_agent`` are voie sa descarce ``url``.

        Fara robots.txt (sau fara un grup care sa se aplice), totul e permis -
        comportamentul standard al crawler-elor.
        """
        rules = self._group_for(user_agent)
        if not rules:
            return True
        parts = urlsplit(url)
        path = parts.path or "/"
        target = f"{path}?{parts.query}" if parts.query else path
        best: _Rule | None = None
        for rule in rules:
            if not rule.regex.match(target):
                continue
            if (
                best is None
                or rule.specificity > best.specificity
                or (rule.specificity == best.specificity and rule.allow and not best.allow)
            ):
                best = rule
        return best.allow if best is not None else True

    def blocks_any_path_for(self, user_agent: str) -> bool:
        """``True`` daca ``user_agent`` are macar o regula ``Disallow`` efectiva.

        Folosit de verificarea GEO: ne intereseaza daca agentul e tinut afara
        de pe site, nu daca i se ascunde ``/admin``. De aceea intrebam doar
        despre radacina.
        """
        return not self.is_allowed("/", user_agent)


def parse_robots_txt(text: str | None) -> RobotsTxt:
    """Parseaza continutul unui robots.txt. Determinist: acelasi text, acelasi rezultat."""
    if text is None:
        return RobotsTxt(fetched=False)

    parsed = RobotsTxt(fetched=True)
    current_agents: list[str] = []
    # Liniile user-agent consecutive formeaza un singur grup; prima linie de
    # regula dupa ele inchide lista si porneste un grup nou la urmatorul agent.
    starting_group = True

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        key = field_name.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if not starting_group:
                current_agents = []
                starting_group = True
            if value:
                current_agents.append(value.lower())
                parsed.groups.setdefault(value.lower(), [])
            continue

        if key == "sitemap":
            if value:
                parsed.sitemaps.append(value)
            continue

        if key in ("allow", "disallow"):
            starting_group = False
            if not current_agents:
                continue
            if not value:
                # "Disallow:" gol = permite tot; "Allow:" gol e ignorat de Google.
                # In ambele cazuri nu se adauga nicio regula.
                continue
            path = unquote(value)
            rule = _Rule(allow=key == "allow", pattern=path, regex=_compile_path_pattern(path))
            for agent in current_agents:
                parsed.groups[agent].append(rule)

    return parsed
