"""Sincronizarea zilnica a pozitiilor in SERP, prin OpenSERP.

Acelasi contract ca restul job-urilor din ``tasks.py``: isi deschide propria
sesiune DB, accepta doar argumente serializabile, merge identic inline sau
intr-un worker ARQ.

Job-ul asta e singurul din proiect care trage de o resursa pe care o poate
PIERDE: OpenSERP conduce un browser headless impotriva Google, iar o rafala de
cereri duce la CAPTCHA si, in cel mai rau caz, la blocarea IP-ului. De aceea
are doua masuri pe care celelalte job-uri nu le au:

- **pauza cu jitter intre interogari** - nu un interval fix, fiindca un ritm
  perfect regulat e in sine un semnal de automatizare;
- **oprire la primul ``blocked``** - raspunsul corect la o provocare anti-bot
  nu e sa mergi mai departe prin restul cuvintelor (asta adanceste blocarea),
  ci sa te opresti si sa raportezi. Cuvintele neverificate raman pur si simplu
  fara rand nou in ziua aia, ceea ce inseamna exact "n-am verificat" - distinct
  de ``rank=None``, care inseamna "am verificat si nu apare".

Deliberat NU foloseste ``OpenSerpProvider.check_rankings`` (calea concurenta):
acolo doua interogari sunt mereu in zbor, deci oprirea la ``blocked`` ar veni
mereu cu o cerere intarziat. Aici pretul e timpul, si timpul il avem.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from ppc_agent.config import Settings
from ppc_agent.search_data.serp_tracker import OpenSerpProvider, SerpCheck
from ppc_agent_server.db import get_engine
from ppc_agent_server.models import ClientAccount, SerpPosition, SerpSource, TrackedKeyword

logger = logging.getLogger("ppc_agent_server.jobs.serp_sync")

#: Pauza intre doua interogari, in secunde. Interval, nu valoare fixa - vezi
#: docstring-ul modulului. Generos intentionat: un audit de pozitii nu e urgent.
MIN_DELAY_SECONDS = 3.0
MAX_DELAY_SECONDS = 9.0


def _build_provider(settings: Settings) -> OpenSerpProvider:
    return OpenSerpProvider(
        base_url=settings.openserp_url,
        language=settings.openserp_language,
        region=settings.openserp_region,
    )


def _sleep_with_jitter() -> None:
    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))


def _to_row(client_account_id: int, check: SerpCheck, checked_on: datetime) -> SerpPosition:
    """Un rezultat de verificare devine un rand de istoric.

    ``rank`` ramane ``None`` cand domeniul nu apare in rezultatele citite -
    informatie reala, nu date lipsa.
    """
    return SerpPosition(
        client_account_id=client_account_id,
        checked_on=checked_on,
        keyword=check.keyword,
        domain=check.domain,
        source=SerpSource.OPENSERP,
        rank=float(check.position) if check.position is not None else None,
        page_url=check.url or "",
    )


def run_serp_sync_job(
    *, client_account_id: int, max_keywords: int = 200, sleep_between: bool = True
) -> dict[str, Any]:
    """Verifica pozitiile pentru cuvintele active ale unui client si le salveaza.

    Args:
        max_keywords: plafon de siguranta pentru o rulare. Peste el, cuvintele
            ramase se verifica la rularea urmatoare.
        sleep_between: ``False`` doar in teste - pauzele cu jitter sunt exact
            ce face job-ul asta sigur in productie.

    Returns:
        Un rezumat cu ce s-a verificat, ce s-a salvat si de ce s-a oprit.
        Nu ridica exceptii pentru probleme de retea: un OpenSERP oprit sau un
        Google care blocheaza sunt stari asteptate, raportate in rezultat.
    """
    checked_on = datetime.now(tz=UTC)
    with Session(get_engine()) as session:
        account = session.get(ClientAccount, client_account_id)
        if account is None:
            return {"error": "clientul nu exista", "client_account_id": client_account_id}
        domain = account.target_domain.strip()
        if not domain:
            return {
                "client_account_id": client_account_id,
                "skipped": "clientul nu are target_domain setat",
            }

        keywords = list(
            session.exec(
                select(TrackedKeyword)
                .where(TrackedKeyword.client_account_id == client_account_id)
                .where(TrackedKeyword.is_active)
                .order_by(TrackedKeyword.id)  # type: ignore[arg-type]
                .limit(max_keywords)
            ).all()
        )
        if not keywords:
            return {"client_account_id": client_account_id, "checked": 0, "saved": 0}

        provider = _build_provider(Settings())
        saved = 0
        checked = 0
        halted_reason = ""

        for index, tracked in enumerate(keywords):
            check = asyncio.run(provider.check_ranking(tracked.keyword, domain))
            checked += 1

            if check.status == "blocked":
                # Ne oprim AICI, nu la finalul buclei: fiecare interogare in plus
                # dupa o provocare anti-bot inrautateste blocarea.
                logger.warning(
                    "ALERTA: Google a blocat verificarile pentru clientul %s la cuvantul '%s'. "
                    "Opresc sincronizarea. %s",
                    client_account_id,
                    tracked.keyword,
                    check.message,
                )
                halted_reason = "blocked"
                break
            if check.status == "unavailable":
                logger.warning(
                    "OpenSERP indisponibil pentru clientul %s: %s",
                    client_account_id,
                    check.message,
                )
                halted_reason = "unavailable"
                break
            if check.status == "error":
                # O eroare punctuala pe un cuvant nu opreste restul - spre
                # deosebire de blocare, nu se agraveaza prin continuare.
                logger.info("verificare esuata pentru '%s': %s", tracked.keyword, check.message)
                continue

            session.add(_to_row(client_account_id, check, checked_on))
            saved += 1

            if sleep_between and index < len(keywords) - 1:
                _sleep_with_jitter()

        session.commit()

    return {
        "client_account_id": client_account_id,
        "keywords_total": len(keywords),
        "checked": checked,
        "saved": saved,
        "halted": halted_reason,
    }


def run_serp_sync_all_clients(*, sleep_between: bool = True) -> dict[str, Any]:
    """Ruleaza sincronizarea pentru toti clientii cu cuvinte urmarite.

    Punct de intrare pentru cron (acelasi tipar ca ``run_daily_maintenance_job``
    din ``tasks.py``): un client blocat nu-i opreste pe ceilalti, dar starea lui
    se vede in rezultat.
    """
    with Session(get_engine()) as session:
        client_ids = list(
            session.exec(select(TrackedKeyword.client_account_id).distinct()).all()
        )

    per_client: dict[str, Any] = {}
    for client_id in client_ids:
        try:
            per_client[str(client_id)] = run_serp_sync_job(
                client_account_id=client_id, sleep_between=sleep_between
            )
        except Exception as exc:
            per_client[str(client_id)] = {"error": f"{type(exc).__name__}: {exc}"}
    return {"clients_processed": len(client_ids), "results": per_client}
