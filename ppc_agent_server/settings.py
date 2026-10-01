"""Configuratia serverului: variabile de mediu, fara prefix (``DATABASE_URL`` etc.).

Separata deliberat de ``ppc_agent.config.Settings`` (care are ``extra="ignore"``,
deci coexista fara conflict in acelasi ``.env`` — CLI-ul ignora pur si simplu
variabilele de server pe care nu le recunoaste).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SQLITE_URL = "sqlite:///./ppc_agent_server.db"

#: Serverul Ollama local (Sistemul 2, vezi ``services/llm_client.py``).
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OLLAMA_DEFAULT_PORT = 11434
#: Adresele pe care ASCULTA un server ("toate interfetele") - nu se poate conecta nimeni la ele.
_BIND_ALL = frozenset({"0.0.0.0", "::"})


def normalize_ollama_host(value: str) -> str:
    """Adresa serverului Ollama, citita ca de clientul oficial ``ollama``.

    ``gazda`` / ``gazda:port`` -> ``http://gazda:port`` (portul implicit 11434); cu
    schema scrisa, portul implicit e al schemei. ``0.0.0.0`` - adresa pe care o da
    documentatia Ollama *serverului* (acelasi ``OLLAMA_HOST``), ca sa-l vada Docker -
    devine ``127.0.0.1``: la ea nu se poate conecta nimeni. Gol = fara Ollama.

    Raises:
        ValueError: nu e o adresa ``http(s)://gazda[:port][/cale]``.
    """
    raw = value.strip()
    if not raw:
        return ""
    has_scheme = "://" in raw
    parts = urlsplit(raw if has_scheme else f"http://{raw}")
    problem = "OLLAMA_HOST trebuie să fie o adresă http(s)://gazdă[:port], fără cont sau query"
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(problem) from exc
    host = parts.hostname
    if (
        parts.scheme not in ("http", "https")
        or not host
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError(problem)
    if host in _BIND_ALL:
        host = "127.0.0.1"
    if port is None:
        port = (443 if parts.scheme == "https" else 80) if has_scheme else OLLAMA_DEFAULT_PORT
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


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

    # Arhitectura hibrida (services/llm_client.py). Sistemul 1 - Jev (TypeSafe AI):
    # deciziile structurate si rapide (scorurile RICE ale CPO-ului, relevanta
    # fragmentelor web ale Researcher-ului). Cheie de pe console.typesafe.ai.
    # Necompletat => reguli fixe (estimarile RICE din tabel, toate fragmentele web).
    jev_api_key: str = ""
    # Sistemul 2 - Ollama, local: tot textul scris (vocea Reginei, consiliul, sinteza).
    # Necompletat => mesajele vin din template-urile interne, fara niciun model.
    ollama_host: str = DEFAULT_OLLAMA_HOST
    # Necompletat => DEFAULT_OLLAMA_MODEL din services/llm_client.py ("llama3", acelasi
    # ca la copywriterul din CLI - un singur `ollama pull`). Accepta si "ollama/<tag>".
    ollama_model: str = ""
    # Circuit-breaker-ul: fara niciun token in atatea secunde, Ollama intra in pauza si
    # raspunde template-ul. Cat timp tokenii curg, generarea nu mai are termen de raspuns.
    # 180 s: pe CPU, sinteza consiliului (~2-3k tokeni de prompt) porneste in ~45 s.
    ollama_first_token_timeout: float = Field(default=180.0, gt=0)
    # Cate generari deodata pe serverul Ollama. 1 pe CPU (le-ar lua oricum pe rand);
    # cu GPU, cat OLLAMA_NUM_PARALLEL-ul serverului.
    ollama_max_parallel: int = Field(default=1, ge=1)
    # Cat tine Ollama modelul incarcat intre cereri (ex. "30m", "2h", "-1" = mereu).
    # Necompletat => implicitul serverului (5 min), dupa care prima cerere il reincarca.
    ollama_keep_alive: str = "30m"
    # Textele Reginei scrise de Ollama: sinteza consiliului si mesajul CMO. Oprite
    # implicit: pe CPU, un model mic scrie
    # zeci de secunde un text pe care garzile il resping des; raspunsul determinist
    # pleaca instant. Porneste-o cu un model mare pe GPU.
    use_llm_synthesis: bool = False
    # Modelul Ollama cu vision pentru evaluarea creativelor (CCO, POST /creative/upload),
    # ex. "qwen2.5vl:3b" sau "llava:7b". Gol = evaluarea raspunde 503 (nu e configurata).
    ollama_vision_model: str = ""
    # Scutul financiar al pilotului: suma bugetelor zilnice angajate pe TOATA
    # platforma (toti clientii, toate propunerile executate sau in curs) nu trece
    # de aici, orice ar permite limita fiecarui client. Moneda contului Meta
    # (PPC_META_CURRENCY) trebuie sa fie RON. Ridic-o deliberat cand pilotul creste.
    max_daily_spend_ron: Decimal = Field(default=Decimal("50"), gt=0)
    # Codul "Test Events" din Events Manager: cu el, conversiile trimise prin
    # Conversions API apar doar in tab-ul de test si NU antreneaza optimizarea Meta.
    # Completat la inceputul pilotului, golit dupa ce evenimentele arata corect.
    meta_capi_test_event_code: str = ""

    @field_validator("jev_api_key", "ollama_model", "ollama_keep_alive", "ollama_vision_model")
    @classmethod
    def _no_blanks(cls, value: str) -> str:
        value = value.strip()
        if any(char.isspace() for char in value):
            raise ValueError("nu poate conține spații")
        return value

    @field_validator("ollama_host")
    @classmethod
    def _ollama_host(cls, value: str) -> str:
        return normalize_ollama_host(value)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_server_settings() -> ServerSettings:
    """Setarile serverului, incarcate o singura data (cache pe proces)."""
    return ServerSettings()
