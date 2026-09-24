"""Executarea unei propuneri aprobate pe platforma de reclame.

Ultimul pas al portii HITL: pana aici totul e propunere, de aici incolo se
schimba ceva real intr-un cont pe care clientul plateste bani. De asta modulul
are trei reguli pe care nu le incalca:

1. **Executa doar din ``PENDING``.** O propunere deja executata, respinsa sau
   picata nu se re-executa: un dublu-click pe butonul de aprobare nu trebuie sa
   dubleze o schimbare de buget - sau sa lanseze a doua campanie.
2. **Nu ghiceste niciodata cum se aplica ceva.** Fiecare resursa se rezolva
   intai intr-un :class:`ResourceTarget` (platforma + tip de obiect + id), si
   doar perechile din :data:`EXECUTORS` se aplica. Ce nu e acolo NU se aplica
   "pe aproape" - pica explicit cu :class:`NoExecutorError`.
3. **Nu trimite un id catre platforma gresita.** Propunerile din motorul hibrid
   (``ppc_keyword``/``keyword_budget``) poarta un TERMEN DE CAUTARE Google Ads,
   nu un id de obiect Meta. Trimis la Graph API, "service auto" ar fi un id
   invalid in cel mai bun caz si un obiect strain in cel mai rau. Rezolvarea
   marcheaza explicit platforma fiecarei resurse, tocmai ca asta sa nu se poata
   intampla - vezi :func:`resolve_target`.

Lansarea unei campanii noi (``CREATE_CAMPAIGN``) bate in contul de reclame,
fiindca campania nu exista inca. Specificatia vine din ``proposal.after`` si se
valideaza din nou aici, INAINTE de orice apel - ce a fost aprobat e ce se
executa, sau nimic.

Modulul nu stie nimic despre HTTP si nici despre SQLModel: primeste obiectul
propunerii si un provider capabil de mutatii, si intoarce ce s-a intamplat.
Persistenta o face apelantul (vezi ``ppc_agent_server/routers/proposals.py``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from ppc_agent.errors import CampaignLaunchError, PpcAgentError
from ppc_agent.providers.meta_campaign import LaunchResult, MetaLaunchSpec

logger = logging.getLogger("ppc_agent.services.execution_engine")


class ProposalNotExecutableError(PpcAgentError):
    """Propunerea nu e intr-o stare din care se poate executa."""


class NoExecutorError(PpcAgentError):
    """Nu stim sa aplicam aceasta propunere.

    Distinct de o eroare a platformei: aici nu platforma a refuzat, ci NOI nu
    stim sa aplicam acest tip de schimbare. Mesajul o spune ca atare, ca omul
    sa nu reincerce degeaba.
    """


#: Platformele pe care le poate tinti o propunere. Sirurile astea ajung si in
#: ``routers/proposals.py``, care alege providerul dupa ele.
PLATFORM_META = "meta"
PLATFORM_GOOGLE_ADS = "google_ads"
PLATFORM_TIKTOK = "tiktok"


class MetaMutationProvider(Protocol):
    """Ce trebuie sa stie face un provider Meta ca sa poata aplica o propunere.

    Deliberat mai ingusta decat ``providers.base.MetaMarketingProvider``: aceea
    e un contract de CITIRE, cablat in Modulele 2 si 3, si nu se schimba pentru
    asta. Aici ne trebuie strict mutatiile, iar un dublu ingust se scrie
    intr-un test fara sa implementeze si ``ad_sets``/``campaign_performance``.
    """

    async def pause_campaign(self, campaign_id: str) -> None: ...
    async def pause_adset(self, adset_id: str) -> None: ...
    async def pause_ad(self, ad_id: str) -> None: ...
    async def update_budget(self, object_id: str, new_daily_budget: Decimal) -> None: ...
    async def launch_campaign(self, ad_account_id: str, spec: MetaLaunchSpec) -> LaunchResult: ...


class ExecutableProposal(Protocol):
    """Ce ii trebuie motorului dintr-o propunere - nu randul intreg din DB."""

    @property
    def op(self) -> str: ...
    @property
    def resource(self) -> str: ...
    @property
    def resource_type(self) -> str: ...
    @property
    def projected_daily_spend(self) -> Decimal: ...
    @property
    def after(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ResourceTarget:
    """Unde bate efectiv o propunere: ce platforma, ce fel de obiect, ce id."""

    platform: str
    kind: str
    object_id: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Ce s-a intamplat cu o executie. ``error`` e gol doar cand a reusit.

    ``created`` poarta id-urile intoarse de platforma: la o lansare reusita,
    obiectele create; la una picata, campania pe care rollback-ul n-a putut-o
    sterge - ca sa apara in date, nu doar intr-un text.
    """

    executed: bool
    detail: str
    error: str = ""
    created: dict[str, str] = field(default_factory=dict)


#: Prefixul resursei spune platforma si tipul obiectului. Numele vin din
#: ``guardrails/pipeline.py`` si ``routers/campaigns.py``, care le construiesc -
#: nu inventa altele aici fara sa le schimbi si acolo.
_RESOURCE_PREFIXES: dict[str, tuple[str, str]] = {
    "meta_campaign/": (PLATFORM_META, "campaign"),
    "meta_ad_set/": (PLATFORM_META, "ad_set"),
    "meta_ad/": (PLATFORM_META, "ad"),
    "campaign/": (PLATFORM_GOOGLE_ADS, "campaign"),
    "tiktok_ad_group/": (PLATFORM_TIKTOK, "ad_group"),
    "negative_keyword/": (PLATFORM_GOOGLE_ADS, "negative_keyword"),
    # Tinta unei lansari (CREATE_CAMPAIGN) e contul de reclame - campania nu
    # exista inca, deci n-are id.
    "meta_ad_account/": (PLATFORM_META, "ad_account"),
}

#: ``ad_set_group/{merged_id}`` (consolidarile de lichiditate, Modulul 3) are
#: acelasi ``resource_type`` ca un set de reclame real, dar id-ul e SINTETIZAT
#: de noi - nu exista asa ceva in contul Meta. Il oprim pe nume, nu pe tip.
_MERGED_AD_SET_PREFIX = "ad_set_group/"

#: Tipurile fara prefix in resursa: acolo ``resource`` e chiar termenul de
#: cautare / cuvantul cheie, iar platforma e Google Ads (motorul hibrid si
#: unealta MCP produc numai asta).
_TYPES_WITHOUT_PREFIX: dict[str, tuple[str, str]] = {
    "ppc_keyword": (PLATFORM_GOOGLE_ADS, "keyword"),
    "keyword_budget": (PLATFORM_GOOGLE_ADS, "keyword"),
}


def resolve_target(proposal: ExecutableProposal) -> ResourceTarget:
    """Spune pe ce platforma si pe ce obiect bate ``proposal``.

    Args:
        proposal: Propunerea de aplicat.

    Returns:
        :class:`ResourceTarget` cu platforma, tipul obiectului si id-ul curat
        (fara prefix).

    Raises:
        NoExecutorError: resursa nu se poate adresa pe nicio platforma.

    Functie pura - apelantul o poate folosi ca sa aleaga providerul INAINTE de
    a incepe executia.
    """
    resource = proposal.resource.strip()
    for prefix, (platform, kind) in _RESOURCE_PREFIXES.items():
        if resource.startswith(prefix):
            object_id = resource[len(prefix) :].strip()
            if not object_id:
                raise NoExecutorError(
                    f"resursa '{resource}' nu contine niciun id dupa prefix"
                )
            return ResourceTarget(platform=platform, kind=kind, object_id=object_id)

    if resource.startswith(_MERGED_AD_SET_PREFIX):
        raise NoExecutorError(
            f"'{resource}' e o consolidare propusa, nu un set de reclame existent: "
            "id-ul e sintetizat de noi, nu exista in contul Meta. Consolidarea se "
            "face manual in Ads Manager."
        )

    platform_kind = _TYPES_WITHOUT_PREFIX.get(proposal.resource_type)
    if platform_kind is not None:
        return ResourceTarget(
            platform=platform_kind[0], kind=platform_kind[1], object_id=resource
        )

    raise NoExecutorError(
        f"nu stiu ce obiect desemneaza resursa '{resource}' "
        f"(tip '{proposal.resource_type}') - aplic-o manual in platforma."
    )


#: Cum se aplica o pereche (platforma, tip de obiect). Primeste providerul,
#: propunerea si tinta rezolvata; intoarce ce s-a intamplat.
#: ``Coroutine``, nu ``Awaitable``: ``asyncio.run`` primeste strict corutine, iar
#: fiecare executor e o functie ``async def``.
Executor = Callable[
    [MetaMutationProvider, ExecutableProposal, ResourceTarget],
    Coroutine[Any, Any, ExecutionResult],
]


async def _update_meta_budget(
    provider: MetaMutationProvider, proposal: ExecutableProposal, target: ResourceTarget
) -> ExecutionResult:
    await provider.update_budget(target.object_id, proposal.projected_daily_spend)
    return ExecutionResult(
        executed=True,
        detail=(
            f"buget zilnic actualizat pe {target.kind} Meta {target.object_id} la "
            f"{proposal.projected_daily_spend}"
        ),
    )


def _unsupported_op(
    proposal: ExecutableProposal, target: ResourceTarget
) -> NoExecutorError:
    return NoExecutorError(
        f"operatia '{proposal.op}' nu are executor pentru {target.kind} pe "
        f"{target.platform} - se aplica manual in platforma"
    )


async def _execute_meta_campaign(
    provider: MetaMutationProvider, proposal: ExecutableProposal, target: ResourceTarget
) -> ExecutionResult:
    if proposal.op == "PAUSE":
        await provider.pause_campaign(target.object_id)
        return ExecutionResult(
            executed=True, detail=f"campanie Meta {target.object_id} pusa pe pauza"
        )
    if proposal.op == "UPDATE":
        return await _update_meta_budget(provider, proposal, target)
    raise _unsupported_op(proposal, target)


async def _execute_meta_ad_set(
    provider: MetaMutationProvider, proposal: ExecutableProposal, target: ResourceTarget
) -> ExecutionResult:
    if proposal.op == "PAUSE":
        await provider.pause_adset(target.object_id)
        return ExecutionResult(
            executed=True, detail=f"set de reclame Meta {target.object_id} pus pe pauza"
        )
    if proposal.op == "UPDATE":
        return await _update_meta_budget(provider, proposal, target)
    raise _unsupported_op(proposal, target)


async def _execute_meta_ad(
    provider: MetaMutationProvider, proposal: ExecutableProposal, target: ResourceTarget
) -> ExecutionResult:
    if proposal.op == "PAUSE":
        await provider.pause_ad(target.object_id)
        return ExecutionResult(executed=True, detail=f"anunt Meta {target.object_id} pus pe pauza")
    raise _unsupported_op(proposal, target)


def _launch_spec(proposal: ExecutableProposal) -> MetaLaunchSpec:
    """Specificatia salvata in propunere, validata INAINTE de orice apel Meta.

    O specificatie care nu mai trece validarea (salvata de o alta versiune a
    codului, sau modificata direct in baza de date) nu se executa pe ghicite:
    propunerea ramane in asteptare, cu motivul, ca omul sa o respinga.
    """
    try:
        return MetaLaunchSpec.from_payload(proposal.after)
    except ValueError as exc:
        raise NoExecutorError(
            f"specificatia de lansare din propunere nu e valida: {exc}. Respinge "
            "propunerea si propune lansarea din nou."
        ) from exc


async def _execute_meta_ad_account(
    provider: MetaMutationProvider, proposal: ExecutableProposal, target: ResourceTarget
) -> ExecutionResult:
    """Lansarea unei campanii noi in contul de reclame ``target.object_id``."""
    if proposal.op != "CREATE_CAMPAIGN":
        raise _unsupported_op(proposal, target)
    spec = _launch_spec(proposal)
    launched = await provider.launch_campaign(target.object_id, spec)
    return ExecutionResult(
        executed=True,
        detail=(
            f"campanie lansata OPRITA in {target.object_id}: campanie "
            f"{launched.campaign_id}, set de reclame {launched.adset_id}, anunt "
            f"{launched.ad_id} - se activeaza manual din Ads Manager, dupa verificare"
        ),
        created=launched.as_dict(),
    )


#: Registrul de executori, pe (platforma, tip de obiect). O pereche care nu e
#: aici NU se aplica - pica explicit cu :class:`NoExecutorError`.
#:
#: Google Ads si TikTok lipsesc DELIBERAT: ``GoogleAdsProvider`` si
#: ``TikTokAdsProvider`` sunt contracte de citire, fara nicio metoda de mutatie
#: si fara implementare in spate. Pana cand capata una, propunerile lor raman
#: in asteptare cu un mesaj care spune exact asta, in loc sa fie trimise la
#: Graph API-ul Meta doar fiindca ala e singurul provider care stie sa scrie.
EXECUTORS: dict[tuple[str, str], Executor] = {
    (PLATFORM_META, "campaign"): _execute_meta_campaign,
    (PLATFORM_META, "ad_set"): _execute_meta_ad_set,
    (PLATFORM_META, "ad"): _execute_meta_ad,
    (PLATFORM_META, "ad_account"): _execute_meta_ad_account,
}


def _leftovers(exc: Exception) -> dict[str, str]:
    """Ce a ramas in cont dupa un esec, ca sa apara in date, nu doar in text.

    Singurul caz: o lansare a carei campanie n-a putut fi stearsa de rollback.
    E oprita, dar are buget - la un click distanta de cheltuiala.
    """
    if isinstance(exc, CampaignLaunchError) and exc.campaign_id and not exc.rolled_back:
        return {"orphan_campaign_id": exc.campaign_id}
    return {}


def execute_proposal(
    proposal: ExecutableProposal,
    provider: MetaMutationProvider,
    *,
    current_status: str,
) -> ExecutionResult:
    """Aplica ``proposal`` pe platforma reala si spune ce s-a intamplat.

    Args:
        proposal: Propunerea de aplicat.
        provider: Providerul platformei pe care bate propunerea. Apelantul il
            alege dupa :func:`resolve_target`, deci trebuie sa fie al aceleiasi
            platforme - motorul nu il poate verifica.
        current_status: starea propunerii inainte de executie. Se primeste
            explicit ca motorul sa nu depinda de enum-ul de persistenta.

    Returns:
        :class:`ExecutionResult` - ``executed=False`` cu ``error`` completat
        cand platforma a refuzat. Apelantul decide ce scrie in baza de date.

    Raises:
        ProposalNotExecutableError: propunerea nu e in ``pending``.
        NoExecutorError: resursa nu se poate adresa, perechea (platforma, tip)
            nu are executor, sau specificatia unei lansari nu e valida.

    Cele doua exceptii sunt RIDICATE, nu intoarse ca rezultat: amandoua inseamna
    ca executia nici nu a inceput, deci propunerea trebuie sa ramana neatinsa,
    nu marcata ca picata.

    Functia e SINCRONA desi providerele scriu async: e puntea catre stratul de
    rute/joburi, care e sincron (la fel ca
    ``search_data/serp_tracker.py::check_rankings_sync``). De evitat apelarea
    ei dintr-o bucla de evenimente deja pornita - ``asyncio.run`` ar crapa
    acolo; in cod async, cheama direct metodele providerului.
    """
    if current_status != "pending":
        raise ProposalNotExecutableError(
            f"doar propunerile in asteptare se pot executa (aceasta e '{current_status}')"
        )

    target = resolve_target(proposal)
    executor = EXECUTORS.get((target.platform, target.kind))
    if executor is None:
        raise NoExecutorError(
            f"nu exista inca un provider care sa aplice schimbari de tip "
            f"'{target.kind}' pe {target.platform}. Propunerea ramane in "
            "asteptare - aplic-o manual in platforma."
        )

    try:
        result = asyncio.run(executor(provider, proposal, target))
    except NoExecutorError:
        raise
    except Exception as exc:
        # Orice esec al platformei (token expirat, obiect sters, buget sub minim,
        # retea) devine un rezultat, nu o exceptie: propunerea trebuie marcata
        # FAILED cu motiv, ca omul sa stie daca reincercarea are sens.
        logger.warning(
            "executie esuata pentru '%s' (%s/%s): %s: %s",
            proposal.resource,
            target.platform,
            target.kind,
            type(exc).__name__,
            exc,
        )
        return ExecutionResult(
            executed=False,
            detail="",
            error=f"{type(exc).__name__}: {exc}",
            created=_leftovers(exc),
        )

    logger.info("executat: %s", result.detail)
    return result
