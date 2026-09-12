"""Incarcarea configuratiei: variabile de mediu (``.env``) plus ``config.yaml``.

- :class:`Settings` citeste valorile sensibile din mediu / ``.env`` (prefix ``PPC_``).
- :class:`AppConfig` combina un ``config.yaml`` optional cu :class:`Settings` intr-un
  singur obiect tipizat, folosit de restul aplicatiei.
- :func:`load_config` este punctul de intrare.
"""

from __future__ import annotations

import enum
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderMode(enum.StrEnum):
    """Sursa datelor pentru adaptoarele externe."""

    MOCK = "mock"
    LIVE = "live"


class Settings(BaseSettings):
    """Valori sensibile / de mediu, citite din mediul de sistem sau din ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="PPC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider_mode: ProviderMode = ProviderMode.MOCK

    # Google Ads API
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_login_customer_id: str = ""

    # Google Search Console + Business Profile (OAuth)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""

    # Meta Marketing API
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""

    # TikTok Ads API
    tiktok_access_token: str = ""
    tiktok_advertiser_id: str = ""

    # Client LLM pentru copywriter (doar pentru PPC_PROVIDER_MODE=live)
    llm_model: str = "ollama/llama3"
    llm_endpoint: str = ""
    # Gol => Ollama decide (GPU daca detecteaza una). Seteaza "0" daca placa video
    # produce raspunsuri corupte/incoerente (vazut cu GPU-uri AMD slabe/nesuportate) —
    # forteaza inferenta pe CPU, care e mereu corecta, doar mai lenta.
    llm_num_gpu: str = ""

    # Modulul 5 — creatii audio/video (doar pentru PPC_PROVIDER_MODE=live)
    fish_speech_url: str = ""
    fish_speech_voice: str = "ro_default"
    flick_endpoint: str = ""
    flick_api_key: str = ""


class BudgetConfig(BaseModel):
    """Limite de buget, in moneda contului (siruri parsate ca ``Decimal``)."""

    model_config = ConfigDict(extra="ignore")

    max_daily_spend: Decimal = Decimal("50.00")
    min_arm_daily_spend: Decimal = Decimal("5.00")
    # Cand e setat, run_plan ridica min_arm_daily_spend peste valoarea de mai sus
    # daca e prea mica pentru buget (vezi decision/budget_strategy.py) - relevant
    # mai ales la conturi cu buget mic. None (implicit) = comportament neschimbat.
    target_cpa: Decimal | None = None


class MetaConfig(BaseModel):
    """Parametri pentru alinierea algoritmica Meta (Modulul 3)."""

    model_config = ConfigDict(extra="ignore")

    target_weekly_conversions: int = 50


class AppConfig(BaseModel):
    """Configuratia completa a aplicatiei: ``config.yaml`` plus :class:`Settings`."""

    model_config = ConfigDict(extra="ignore")

    target_domain: str = "https://exemplu.ro"
    geo: str = "RO"
    language: str = "ro"
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    competitor_brands: list[str] = Field(default_factory=list)
    meta: MetaConfig = Field(default_factory=MetaConfig)
    settings: Settings = Field(default_factory=Settings)

    @property
    def provider_mode(self) -> ProviderMode:
        """Comoditate: modul furnizorilor, preluat din :class:`Settings`."""
        return self.settings.provider_mode


def load_config(config_path: str | Path | None = "config.yaml") -> AppConfig:
    """Construieste :class:`AppConfig` dintr-un ``config.yaml`` optional plus mediul.

    Args:
        config_path: Cale catre fisierul YAML. Daca este ``None`` sau fisierul nu
            exista, se folosesc valorile implicite plus ``.env``.

    Returns:
        Configuratia aplicatiei, complet tipizata.

    Raises:
        yaml.YAMLError: Daca fisierul YAML exista dar nu poate fi parsat.
    """
    data: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {str(key): value for key, value in loaded.items()}

    merged: dict[str, Any] = {**data, "settings": Settings()}
    return AppConfig.model_validate(merged)
