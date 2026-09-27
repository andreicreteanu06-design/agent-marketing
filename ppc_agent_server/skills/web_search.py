"""Abilitatea ``web_search``: DuckDuckGo prin ``ddgs`` (fara cheie), rezultate din Romania.

Mutata din Researcher (``researcher.py``), care o cere acum prin registru. Singura
cerere reala e :func:`ddgs_text`; restul pastreaza doar titlul, fragmentul si
site-ul sursa (fara link) si tine rezultatele minte o zi.
"""

from __future__ import annotations

import asyncio
from datetime import date
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from ddgs import DDGS
from pydantic import BaseModel

from ppc_agent_server.skills.registry import BaseAgentSkill

#: Rezultate cerute per interogare si timeout-ul unei cereri.
WEB_RESULTS_PER_QUERY = 5
WEB_TIMEOUT_SECONDS = 8.0


class WebFinding(BaseModel):
    """Un rezultat al cautarii pe web: titlul, fragmentul si site-ul (fara link)."""

    query: str
    title: str
    snippet: str
    source: str


def _short(text: str, limit: int = 150) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def ddgs_text(query: str) -> list[dict[str, Any]]:
    """Singura cerere reala: DuckDuckGo prin ``ddgs`` (fara cheie), rezultate din Romania."""
    return DDGS(timeout=int(WEB_TIMEOUT_SECONDS)).text(
        query, region="ro-ro", safesearch="moderate", max_results=WEB_RESULTS_PER_QUERY
    )


def _finding(query: str, result: dict[str, Any]) -> WebFinding | None:
    title = " ".join(str(result.get("title") or "").split())
    snippet = " ".join(str(result.get("body") or "").split())
    source = (urlsplit(str(result.get("href") or "")).hostname or "").removeprefix("www.")
    if not (title and snippet and source):
        return None
    return WebFinding(
        query=query, title=_short(title, 120), snippet=_short(snippet, 300), source=source
    )


@lru_cache(maxsize=256)
def _cached_search(query: str, day: date) -> tuple[WebFinding, ...]:
    # ponytail: cache pe proces, o zi (cheia contine ziua); DuckDuckGo limiteaza
    # repede, iar chatul intreaba de mai multe ori pe zi acelasi lucru. Erorile nu
    # se tin minte (exceptiile nu intra in lru_cache). Redis, daca sunt mai multi workeri.
    found = (_finding(query, result) for result in ddgs_text(query))
    return tuple(finding for finding in found if finding is not None)


class WebSearchSkill(BaseAgentSkill):
    name = "web_search"
    description = (
        "Caută pe web (DuckDuckGo, rezultate din România) și întoarce primele fragmente, cu "
        "site-ul sursă, fără linkuri. Argument: query (textul căutării)."
    )

    async def execute(self, **kwargs: Any) -> list[WebFinding]:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("web_search cere un «query» nevid")
        # Cererea e blocanta: in fir separat, ca sa nu opreasca bucla asyncio.
        return list(await asyncio.to_thread(_cached_search, query.strip(), date.today()))
