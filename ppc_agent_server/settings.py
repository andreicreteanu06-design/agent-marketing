"""Configuratia serverului: variabile de mediu, fara prefix (``DATABASE_URL`` etc.).

Separata deliberat de ``ppc_agent.config.Settings`` (care are ``extra="ignore"``,
deci coexista fara conflict in acelasi ``.env`` — CLI-ul ignora pur si simplu
variabilele de server pe care nu le recunoaste).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SQLITE_URL = "sqlite:///./ppc_agent_server.db"


class ServerSettings(BaseSettings):
    """Valori de mediu pentru ``ppc_agent_server``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Necompletat => SQLite local (fara nimic de instalat) — filozofia mock-first
    # a restului proiectului, aplicata infrastructurii. Seteaza pentru Postgres real.
    database_url: str = _DEFAULT_SQLITE_URL

    # Necompletat => InlineJobQueue (sincron, in proces, ce folosesc testele).
    # Seteaza pentru coada reala ARQ+Redis (Faza F).
    redis_url: str = ""


@lru_cache
def get_server_settings() -> ServerSettings:
    """Setarile serverului, incarcate o singura data (cache pe proces)."""
    return ServerSettings()
