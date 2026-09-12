"""Monitorul de oboseala a anunturilor: Kill Rules, Pruning Switches, tampon CAPI.

``evaluate_ad`` e o functie pura, determinista - trei porti evaluate in ordine:

    Gate A (tampon de atribuire) -> Gate B (anunturi noi) -> Gate C (anunturi
    profitabile)

Niciun apel de retea, nicio dependinta de provideri - primeste starea deja
masurata (:class:`~ppc_agent.decision.fatigue_models.AdPerformanceState`) si
un timestamp, si returneaza un verdict. Constructia unui ``proposed_changes_*.json``
din verdicte (pentru fluxul ``execute`` existent) traieste in
:mod:`ppc_agent.guardrails.pipeline` (``build_fatigue_changes``), nu aici -
acest modul ramane doar motorul de decizie.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ppc_agent.decision.fatigue_models import AdPerformanceState, FatigueVerdict
from ppc_agent.errors import FatigueInputError

# Gate A - tampon de atribuire (CAPI / server-side are nevoie de timp sa se stabilizeze).
_ATTRIBUTION_BUFFER_HOURS = 48.0

# Gate B - Kill Switch (prospectare rece, anunturi noi).
_HARD_KILL_AGE_HOURS = 72.0
_HARD_KILL_SPEND_MULTIPLIER = 2.0
_HARD_KILL_MIN_IMPRESSIONS = 1500
_PROVISIONAL_MIN_IMPRESSIONS = 1500
_PROVISIONAL_CTR_RATIO = 0.50
_PROVISIONAL_MIN_CLICKS = 30
_LAG_HOLD_SPEND_MULTIPLIER = 1.5

# Gate C - Pruning Switch (oboseala creativa, anunturi profitabile), Meta.
_META_MIN_IMPRESSIONS = 1500
_META_CTR_DECLINE_RATIO = 0.75
_META_CPA_INCREASE_RATIO = 1.25
_META_MIN_FREQUENCY = 3.0
_META_MIN_BAD_DAYS = 3

# Gate C, TikTok.
_TIKTOK_MIN_IMPRESSIONS = 2000
_TIKTOK_CTR_DECLINE_RATIO = 0.75
_TIKTOK_CPA_INCREASE_RATIO = 1.25
_TIKTOK_VIEW_RATE_RATIO = 0.80
_TIKTOK_MIN_BAD_DAYS = 2


def new_ad_hard_kill_spend_multiplier() -> float:
    """Multiplicatorul de cheltuiala (fata de ``target_cpa``) folosit de Gate B
    pentru ``PAUSE_HARD`` - expus public pentru ca
    :mod:`ppc_agent.decision.budget_strategy` are nevoie de acelasi prag ca sa
    planifice bugetul minim per brat la conturi cu buget mic. Un singur loc de
    adevar, ca cele doua praguri sa nu diverga in timp.
    """
    return _HARD_KILL_SPEND_MULTIPLIER


def _age_hours(ad: AdPerformanceState, current_time: datetime) -> float:
    return (current_time - ad.launch_time).total_seconds() / 3600


def _evaluate_new_ad(ad: AdPerformanceState, age_hours: float) -> FatigueVerdict:
    """Gate B: Kill Switch pentru anunturi noi (``status == "new"``)."""
    if (
        age_hours >= _HARD_KILL_AGE_HOURS
        and ad.spend >= _HARD_KILL_SPEND_MULTIPLIER * ad.target_cpa
        and ad.conversions == 0
        and ad.impressions >= _HARD_KILL_MIN_IMPRESSIONS
    ):
        return "PAUSE_HARD"
    if (
        ad.impressions >= _PROVISIONAL_MIN_IMPRESSIONS
        and ad.ctr <= _PROVISIONAL_CTR_RATIO * ad.account_median_ctr
        and ad.clicks >= _PROVISIONAL_MIN_CLICKS
    ):
        return "PAUSE_PROVISIONAL"
    if (
        ad.spend >= _LAG_HOLD_SPEND_MULTIPLIER * ad.target_cpa
        and ad.conversions == 0
        and age_hours >= _ATTRIBUTION_BUFFER_HOURS
    ):
        return "HOLD_FOR_LAG"
    return "CONTINUE"


def _evaluate_profitable_ad(ad: AdPerformanceState) -> FatigueVerdict:
    """Gate C: Pruning Switch pentru anunturi profitabile (``status == "profitable"``).

    Fara regula pentru Google (cererea a definit-o explicit doar pentru
    Meta/TikTok) - un anunt Google profitabil trece prin fara sa declanseze
    nimic (``"CONTINUE"``).
    """
    if (
        ad.platform == "meta"
        and ad.impressions >= _META_MIN_IMPRESSIONS
        and ad.ctr_3d <= _META_CTR_DECLINE_RATIO * ad.ctr_baseline_14d
        and ad.cpa_3d >= _META_CPA_INCREASE_RATIO * ad.cpa_baseline_14d
        and ad.frequency_7d >= _META_MIN_FREQUENCY
        and ad.bad_days_last_5 >= _META_MIN_BAD_DAYS
    ):
        return "PAUSE_REPLACE"
    if (
        ad.platform == "tiktok"
        and ad.impressions >= _TIKTOK_MIN_IMPRESSIONS
        and ad.ctr_3d <= _TIKTOK_CTR_DECLINE_RATIO * ad.ctr_baseline_7d
        and ad.cpa_3d >= _TIKTOK_CPA_INCREASE_RATIO * ad.cpa_baseline_7d
        and ad.six_second_view_rate
        <= _TIKTOK_VIEW_RATE_RATIO * ad.six_second_view_rate_baseline
        and ad.bad_days_last_3 >= _TIKTOK_MIN_BAD_DAYS
    ):
        return "PAUSE_REPLACE"
    return "CONTINUE"


def evaluate_ad(ad: AdPerformanceState, current_time: datetime) -> FatigueVerdict:
    """Evalueaza un anunt fata de regulile de Kill Switch / Pruning Switch.

    Args:
        ad: Instantaneul de performanta al anuntului.
        current_time: Momentul evaluarii (de regula ``datetime.now(tz=UTC)``).

    Returns:
        ``"CONTINUE"``: prea devreme pentru o decizie (Gate A), sau anuntul
            nu a declansat nicio regula, sau ``status == "fatigued"`` (deja
            actionat intr-o rulare anterioara - nimic nou de facut).
        ``"PAUSE_HARD"``: anunt nou, fara nicio conversie, cheltuiala >= 2x
            target CPA, varsta >= 72h - oprire cu incredere ridicata.
        ``"PAUSE_PROVISIONAL"``: anunt nou cu CTR mult sub media contului -
            oprire cu incredere mai mica, recomandata revizuirii umane.
        ``"HOLD_FOR_LAG"``: anunt nou care a cheltuit peste prag fara conversii,
            dar prea devreme pentru un kill definitiv - probabil intarziere
            de atribuire, nu neaparat un pierzator.
        ``"PAUSE_REPLACE"``: anunt profitabil, dar cu semne clare de oboseala
            creativa (CTR in scadere, CPA in crestere fata de propriul istoric)
            - de oprit si inlocuit cu o creatie noua.
    """
    age_hours = _age_hours(ad, current_time)

    # Gate A: tampon de atribuire - CAPI/server-side are nevoie de timp sa se stabilizeze.
    if age_hours < _ATTRIBUTION_BUFFER_HOURS:
        return "CONTINUE"

    if ad.status == "new":
        return _evaluate_new_ad(ad, age_hours)
    if ad.status == "profitable":
        return _evaluate_profitable_ad(ad)
    return "CONTINUE"  # status == "fatigued"


def explain_verdict(ad: AdPerformanceState, verdict: FatigueVerdict, current_time: datetime) -> str:
    """Motivul citibil din spatele unui verdict - pentru rationale-ul HITL.

    Separata de :func:`evaluate_ad` (care ramane o functie pura, doar
    verdictul) ca sa poata fi reutilizata atat de CLI (afisare) cat si de
    :func:`ppc_agent.guardrails.pipeline.build_fatigue_changes` (rationale-ul
    din ``ProposedChange``), fara sa duplice logica de portite.
    """
    age_hours = _age_hours(ad, current_time)
    if verdict == "CONTINUE" and age_hours < _ATTRIBUTION_BUFFER_HOURS:
        return (
            f"varsta {age_hours:.1f}h < tamponul de atribuire de "
            f"{_ATTRIBUTION_BUFFER_HOURS:.0f}h"
        )
    if verdict == "PAUSE_HARD":
        return (
            f"Kill Switch: varsta {age_hours:.0f}h, cheltuiala {ad.spend:.2f} >= "
            f"{_HARD_KILL_SPEND_MULTIPLIER:.1f}x target_cpa ({ad.target_cpa:.2f}), "
            f"0 conversii din {ad.impressions} afisari"
        )
    if verdict == "PAUSE_PROVISIONAL":
        return (
            f"CTR {ad.ctr:.4f} <= {_PROVISIONAL_CTR_RATIO:.0%} din media contului "
            f"({ad.account_median_ctr:.4f}), {ad.impressions} afisari, {ad.clicks} click-uri"
        )
    if verdict == "HOLD_FOR_LAG":
        return (
            f"cheltuiala {ad.spend:.2f} >= {_LAG_HOLD_SPEND_MULTIPLIER:.1f}x target_cpa "
            f"({ad.target_cpa:.2f}) fara conversii - posibila intarziere de atribuire"
        )
    if verdict == "PAUSE_REPLACE" and ad.platform == "meta":
        return (
            f"oboseala creativa (Meta): CTR 3z {ad.ctr_3d:.4f} <= "
            f"{_META_CTR_DECLINE_RATIO:.0%} din baza 14z ({ad.ctr_baseline_14d:.4f}), "
            f"CPA 3z {ad.cpa_3d:.2f} >= {_META_CPA_INCREASE_RATIO:.0%} din baza 14z "
            f"({ad.cpa_baseline_14d:.2f}), frecventa {ad.frequency_7d:.1f}, "
            f"{ad.bad_days_last_5} zile proaste din ultimele 5"
        )
    if verdict == "PAUSE_REPLACE" and ad.platform == "tiktok":
        return (
            f"oboseala creativa (TikTok): CTR 3z {ad.ctr_3d:.4f} <= "
            f"{_TIKTOK_CTR_DECLINE_RATIO:.0%} din baza 7z ({ad.ctr_baseline_7d:.4f}), "
            f"CPA 3z {ad.cpa_3d:.2f} >= {_TIKTOK_CPA_INCREASE_RATIO:.0%} din baza 7z "
            f"({ad.cpa_baseline_7d:.2f}), 6s-view-rate {ad.six_second_view_rate:.2f}, "
            f"{ad.bad_days_last_3} zile proaste din ultimele 3"
        )
    return f"fara motiv specific (verdict={verdict}, status={ad.status})"


def load_ad_performance_states(path: Path | str) -> list[AdPerformanceState]:
    """Citeste o lista de :class:`AdPerformanceState` dintr-un fisier JSON.

    Fara sursa live: niciun provider mock din proiect nu produce inca acest
    nivel de detaliu per-anunt (frecventa, CTR/CPA de baza, zile proaste) -
    fisierul e furnizat de operator, ca la ``ingest-tiktok``/``ingest-swipes``.

    Args:
        path: Cale catre un fisier JSON cu o lista de obiecte
            :class:`AdPerformanceState`.

    Returns:
        Lista validata de stari de performanta.

    Raises:
        FatigueInputError: Fisierul lipseste, nu e JSON valid, nu e o lista
            nevida, sau o intrare nu respecta schema.
    """
    resolved = Path(path)
    if not resolved.is_file():
        raise FatigueInputError(f"fisierul nu a fost gasit: {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FatigueInputError(f"fisierul nu e JSON valid: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise FatigueInputError("fisierul trebuie sa contina o lista nevida de anunturi")
    try:
        return [AdPerformanceState.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise FatigueInputError(f"intrare invalida: {exc}") from exc
