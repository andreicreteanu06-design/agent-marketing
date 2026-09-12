"""Tipuri de exceptii partajate de toate modulele agentului PPC."""

from __future__ import annotations


class PpcAgentError(Exception):
    """Clasa de baza pentru toate erorile agentului PPC."""


class SetupRequiredError(PpcAgentError):
    """Ridicata cand se cere modul ``live`` fara integrarea / credentialele necesare.

    In versiunea 1 modul ``live`` este un stub: orice apel catre un furnizor
    ``live`` ridica aceasta eroare cu instructiuni de configurare. Niciun apel de
    retea nu este efectuat.
    """


class ApprovalRequiredError(PpcAgentError):
    """Ridicata cand se incearca executarea unui set de modificari neconfirmat.

    Vezi Modulul 4 (:mod:`ppc_agent.guardrails`). Nicio operatie de scriere nu
    poate ocoli fluxul ``propose -> flush -> confirmare umana``.
    """


class SpendLimitExceeded(PpcAgentError):
    """Ridicata cand cheltuiala zilnica propusa depaseste limita permisa.

    Sursa limitei: fie ``budget.max_daily_spend`` din configuratie, fie plafonul
    absolut hardcodat in :mod:`ppc_agent.guardrails` (Modulul 4).
    """


class CrawlError(PpcAgentError):
    """Eroare la accesarea unei pagini de catre crawler (Modulul 1)."""


class CrawlTimeoutError(CrawlError):
    """Pagina nu a raspuns in intervalul de timp alocat."""


class DecisionError(PpcAgentError):
    """Eroare in motorul matematic de decizie (Modulul 2)."""


class BudgetAllocationError(DecisionError):
    """Intrare invalida pentru alocarea de buget (arme lipsa, buget negativ etc.)."""


class AttributionError(DecisionError):
    """Intrare invalida pentru atribuirea Markov (fara parcursuri sau fara conversii)."""


class FatigueInputError(DecisionError):
    """Fisierul de intrare pentru monitorul de oboseala lipseste sau e invalid.

    Fisierul JSON lipseste, are extensie necunoscuta, sau o intrare nu respecta
    schema :class:`~ppc_agent.decision.fatigue_models.AdPerformanceState`.
    """


class CopywriterError(PpcAgentError):
    """Eroare in modulul de copywriting (generare de anunturi)."""


class SwipeFileError(CopywriterError):
    """``swipe_file.json`` lipseste, e invalid, sau nu contine framework-ul cerut."""


class TikTokIngestError(CopywriterError):
    """Ingestia bibliotecii TikTok a esuat.

    Fisierul de intrare lipseste, are extensie necunoscuta, sau o intrare nu
    respecta schema :class:`~ppc_agent.copywriter.models.TikTokSwipeRecord`.
    """


class SwipeIngestError(CopywriterError):
    """Ingestia bibliotecii omnicanal a esuat.

    Fisierul CSV de intrare lipseste/e gol/are coloane lipsa, un rand nu respecta
    schema :class:`~ppc_agent.copywriter.models.OmniSwipeRecord`, sau
    ``swipe_file.json`` (tinta ingestiei) nu e JSON valid.
    """


class AdsLimitError(CopywriterError):
    """Un text de anunt depaseste limita Google Ads (headline 30 / descriere 90).

    Attributes:
        field: Campul care depaseste (ex. ``headline_1``).
        length: Lungimea reala, in caractere.
        limit: Limita permisa.
    """

    def __init__(self, field: str, length: int, limit: int) -> None:
        self.field = field
        self.length = length
        self.limit = limit
        super().__init__(
            f"{field} are {length} caractere, peste limita Google Ads de {limit}"
        )


class CreativeError(PpcAgentError):
    """Eroare in Modulul 5 (generarea de creatii audio/video)."""


class TtsError(CreativeError):
    """Sinteza vocala (text-to-speech) a esuat."""


class VideoAssemblyError(CreativeError):
    """Asamblarea video (Flick) a esuat sau a primit intrari invalide."""


class StoryboardValidationError(CreativeError):
    """Un storyboard generat nu respecta regulile deterministe de productie video.

    Ridicata de :class:`~ppc_agent.creative.video_qa.StoryboardValidator`.
    Niciun storyboard care incalca ritmul/tipografia/regula CTA/timeline-ul nu
    ajunge sa fie salvat.

    Attributes:
        issues: Toate problemele gasite (nu doar prima).
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        joined = "; ".join(issues)
        super().__init__(f"storyboard invalid ({len(issues)} probleme): {joined}")
