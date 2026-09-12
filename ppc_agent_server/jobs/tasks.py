"""Task-urile efective: wrapper-e subtiri peste pipeline-urile pure din ``ppc_agent``.

Fiecare functie isi deschide propria sesiune DB (nu primeste una de la apelant)
si accepta doar argumente serializabile — functioneaza identic fie apelata
inline (``InlineJobQueue``, Faza E), fie intr-un proces worker ARQ separat
(Faza F), unde nu exista nicio sesiune HTTP de mostenit.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlmodel import Session

from ppc_agent.config import AppConfig, BudgetConfig, Settings
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.creative.creative_pipeline import generate_full_ad_creative
from ppc_agent.creative.factory import CreativeFactory
from ppc_agent.decision.pipeline import run_plan
from ppc_agent.providers.factory import ProviderFactory
from ppc_agent_server.db import get_engine
from ppc_agent_server.models import AdQueueItem, ClientAccount, CreativeArtifact, Platform

AdPlatform = Literal["google", "tiktok"]


class ClientNotFoundError(ValueError):
    """Clientul referit de job nu exista — eroare de date, nu de infrastructura."""


def _app_config_for(account: ClientAccount) -> AppConfig:
    """Construieste un :class:`AppConfig` CLI-compatibil dintr-un rand ``ClientAccount``.

    ``settings=Settings()`` citeste ``PPC_PROVIDER_MODE`` (si restul) din mediu,
    exact ca la CLI — serverul nu reinventeaza o a doua sursa de configurare.

    ``default_lead_value`` alimenteaza ``budget.target_cpa``: acelasi camp
    serveste deja drept proxy de valoare pentru urmarirea conversiilor (vezi
    ``tracking/qualification.py``) si drept ``target_cpa`` la crearea unui
    ``AdPerformanceRecord`` nou (vezi ``tracking/pipeline.py``) — reutilizat
    aici ca sa activeze automat sfatul de capacitate per buget
    (``decision.budget_strategy``) pentru fiecare client, fara camp nou.
    """
    return AppConfig(
        target_domain=account.target_domain,
        geo=account.geo,
        language=account.language,
        budget=BudgetConfig(
            max_daily_spend=account.max_daily_spend,
            target_cpa=account.default_lead_value,
        ),
        settings=Settings(),
    )


def _require_client(session: Session, client_account_id: int) -> ClientAccount:
    account = session.get(ClientAccount, client_account_id)
    if account is None:
        raise ClientNotFoundError(f"clientul {client_account_id} nu exista")
    return account


def run_plan_job(*, client_account_id: int) -> dict[str, Any]:
    """Job Modulul 2: Kelly + Thompson + Markov (Google + TikTok combinate)."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = ProviderFactory(config)
        plan = run_plan(factory, config)
        return plan.model_dump(mode="json")


def run_copy_job(
    *,
    client_account_id: int,
    keyword: str,
    usp: str,
    trigger: str,
    platform: AdPlatform,
) -> dict[str, Any]:
    """Job copywriter: genereaza copy si il salveaza in coada HITL (``AdQueueItem``)."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        llm_client = CreativeFactory(config).llm()
        generator = AdCopyGenerator(llm_client)
        ad_copy = generator.generate_emotional_copy(usp, keyword, trigger, platform)

        item = AdQueueItem(
            client_account_id=client_account_id,
            platform=Platform(platform),
            target_keyword=keyword,
            emotion_trigger=trigger,
            product_usp=usp,
            ad_copy=ad_copy,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {"ad_queue_item_id": item.id, "ad_copy": ad_copy}


def run_creative_job(
    *,
    client_account_id: int,
    keyword: str,
    broll_path: str,
    trigger: str,
    usp: str | None,
    platform: AdPlatform,
) -> dict[str, Any]:
    """Job Modulul 5: genereaza voce + video si inregistreaza artefactul."""
    with Session(get_engine()) as session:
        account = _require_client(session, client_account_id)
        config = _app_config_for(account)
        factory = CreativeFactory(config)
        result = generate_full_ad_creative(
            factory.llm(),
            factory.tts(),
            factory.video(),
            keyword=keyword,
            raw_broll_path=broll_path,
            emotion_trigger=trigger,
            product_usp=usp,
            platform=platform,
        )

        artifact = CreativeArtifact(
            client_account_id=client_account_id,
            platform=Platform(result.platform),
            keyword=keyword,
            wav_path=result.voiceover_path,
            mp4_path=result.mp4_path,
            duration_seconds=result.duration_seconds,
            manifest=result.manifest,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return {"creative_artifact_id": artifact.id, "mp4_path": result.mp4_path}
