"""Configuratia seo_geo_agent: variabile de mediu, prefix ``SEOGEO_``.

O singura variabila face exceptie de la prefix: ``jwt_secret_key`` citeste
direct ``JWT_SECRET_KEY`` (fara prefix) - acelasi secret cu ``ppc_agent_server``
(vezi ``settings.py`` de acolo), ca acest agent sa poata valida token-ul unui
client deja autentificat pe site, fara un al doilea login.
"""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderMode(enum.StrEnum):
    """Sursa raspunsului de analiza."""

    MOCK = "mock"
    LIVE = "live"


class SeoGeoSettings(BaseSettings):
    """Valori de mediu pentru ``seo_geo_agent``."""

    model_config = SettingsConfigDict(
        env_prefix="SEOGEO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Necompletat => MockLLMClient (determinist, fara Ollama pornit). Filozofia
    # mock-first a restului proiectului, aplicata si aici.
    provider_mode: ProviderMode = ProviderMode.MOCK

    # Client LLM (doar pentru SEOGEO_PROVIDER_MODE=live) - Ollama local, gratuit,
    # datele nu parasesc masina. SEOGEO_LLM_MODEL accepta tag-ul cu sau fara
    # prefixul "ollama/" (ex. "llama3", "qwen2.5").
    llm_model: str = "ollama/llama3"
    llm_endpoint: str = ""
    # Gol => Ollama decide (GPU daca detecteaza una). Seteaza "0" pentru a forta CPU.
    llm_num_gpu: str = ""

    # Secretul de semnare JWT - COMUN cu ppc_agent_server (fara prefix, vezi
    # docstring-ul modulului). Fara el, orice cerere catre /analyze primeste 401.
    jwt_secret_key: str = Field(default="", validation_alias="JWT_SECRET_KEY")

    # Originile carora CORSMiddleware le permite cereri din browser (site-ul de
    # marketing). Implicit doar serverul Next.js local. Lista separata prin virgula.
    cors_allowed_origins: str = "http://localhost:3000"

    # --- Auditul determinist (seo_geo_agent/audit/) ---
    # Plafonul absolut de pagini pe care il poate cere un client, indiferent ce
    # trimite in ``max_pages``. Un audit inseamna cate o cerere HTTP per pagina
    # catre site-ul clientului: limita asta e si politete fata de el, si
    # protectie pentru procesul nostru (n-are coada de joburi - vezi audit/store.py).
    audit_max_pages: int = 100
    # Dupa atatea secunde, crawl-ul se opreste si raportul se marcheaza PARTIAL
    # (``completed=false``), in loc sa tina clientul agatat la nesfarsit.
    audit_time_budget_seconds: float = 150.0

    # Optional - vezi external_data.py. Fara ea, PageSpeed Insights functioneaza
    # tot, doar cu o cota mica. Microlink.io/LanguageTool nu au nevoie de cheie.
    pagespeed_api_key: str = ""

    # Optional - vezi external_data.py. Spre deosebire de celelalte 3 surse, fara
    # ea fetch_semantic_embedding nu face niciun apel (Hugging Face refuza cereri
    # anonime pentru majoritatea modelelor). Token gratuit de pe huggingface.co.
    huggingface_api_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_seo_geo_settings() -> SeoGeoSettings:
    """Setarile agentului, incarcate o singura data (cache pe proces)."""
    return SeoGeoSettings()
