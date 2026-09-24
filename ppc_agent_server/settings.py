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

    # Cheie de semnare pentru token-urile JWT ale clientilor (POST /signup,
    # /login) - fara ea, create_client_token()/decode_client_token() ridica
    # RuntimeError (nu exista un implicit nesigur). Genereaz-o o singura data:
    # python -c "import secrets; print(secrets.token_urlsafe(32))"
    jwt_secret_key: str = ""

    # Cheie Fernet pentru criptarea secretelor per-client (refresh/access
    # tokens de pe conturile de reclame) stocate pe ClientAccount - vezi
    # security.py. Genereaz-o o singura data si NU o schimba dupa ce exista
    # secrete criptate cu ea (devin ilizibile):
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secrets_key: str = ""

    # Tenant-ul (agentia) caruia ii apartin conturile create prin semnarea
    # publica (POST /signup) - produsul e single-agentie azi (vezi planul),
    # deci exact un tenant. Fara el configurat, /signup ridica 503 in loc sa
    # ghiceasca primul rand din tabel.
    agency_tenant_id: int | None = None

    # Originile carora CORSMiddleware le permite cereri din browser (site-ul
    # de marketing, servit separat - vezi site/). Lista separata prin virgula.
    # Implicit doar serverul Next.js local (npm run dev, port 3000) - in
    # productie, seteaza domeniul real al site-ului.
    cors_allowed_origins: str = "http://localhost:3000"

    # Conectarea Google (Search Console, Analytics) - vezi routers/integrations.py.
    # Adresa publica a ACESTUI API: din ea se construieste redirect_uri-ul OAuth
    # (.../api/v1/integrations/{gsc|ga4}/callback), care trebuie adaugat EXACT
    # asa la "Authorized redirect URIs" in Google Cloud Console.
    public_api_url: str = "http://localhost:8000"
    # Site-ul pe care se intoarce clientul dupa ecranul de consimtamant Google.
    site_url: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_server_settings() -> ServerSettings:
    """Setarile serverului, incarcate o singura data (cache pe proces)."""
    return ServerSettings()
