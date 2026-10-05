"""Profilul cognitiv al cumparatorului: cum decide, ce il opreste, ce il convinge.

Stratul de neuromarketing al Reginei, peste profilurile MiroFish din
``queen_agent.py``. Trei clasificari deterministe - aceleasi date dau mereu
acelasi profil, iar fiecare concluzie isi arata dovada in cifre:

1. **Modul de decizie** (Kahneman, *Thinking, Fast and Slow*). Pretul, urgenta
   si comoditatea cer o decizie rapida, automata (Sistemul 1): dovada vizuala,
   pretul spus direct, un singur indemn. Increderea si informarea cer efort
   deliberativ (Sistemul 2): specificatii, comparatii, eliminarea riscului.
   Cota fiecarui sistem = cota profilurilor lui in ce aduce contul.
2. **Bariera de conversie**: unde se rupe drumul de la click la cumparare.
   Profilul care converteste mult sub media contului o arata: pretul ->
   *valoare perceputa* (vede pretul, nu vede ce primeste); increderea ->
   *incredere* (McKnight: competenta, integritate, bunavointa percepute);
   urgenta si comoditatea -> *frictiune* (Iyengar: prea multe optiuni sau pasi
   blocheaza alegerea). Cei care se informeaza nu sunt o bariera - nu cumparau.
3. **Ruta de persuasiune** (Elaboration Likelihood Model, Petty & Cacioppo):
   publicul deliberativ se convinge pe ruta centrala (argumente, cifre),
   cel rapid pe ruta periferica (imagine, brand, dovada sociala).

Fara aleator si fara LLM. Fara date suficiente, bariera ramane ``unknown`` -
nu se ghiceste. Modulul nu importa nimic din ``queen_agent`` (acolo e folosit).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel

from ppc_agent.texttools import tokenize
from ppc_agent_server.services.ro_format import count, percent, rate

DecisionSystem = Literal["system_1", "system_2", "mixed"]
AdDemand = Literal["system_1", "system_2"]
BarrierKind = Literal["friction", "trust", "perceived_value", "none", "unknown"]
RouteKind = Literal["central", "peripheral", "dual"]

#: Profilurile care decid deliberativ (Sistemul 2); restul decid rapid (Sistemul 1).
DELIBERATIVE_PROFILES = frozenset({"trust", "research"})
#: De la aceasta cota a profilurilor deliberative, publicul e "Sistemul 2"...
SYSTEM_2_FROM = 0.6
#: ...iar pana la aceasta, "Sistemul 1". Intre ele, public mixt.
SYSTEM_1_UNTIL = 0.4
#: Un profil e bariera cand converteste sub atata din rata medie a contului.
BARRIER_RATE_RATIO = 0.6
#: Sub atatea click-uri platite, rata unui profil e zgomot.
MIN_PAID_CLICKS_FOR_BARRIER = 20
#: Peste atatea cuvinte, o reclama cere citire atenta (Sistemul 2).
LONG_AD_WORDS = 30

_BARRIER_BY_PROFILE: dict[str, BarrierKind] = {
    "price": "perceived_value",
    "trust": "trust",
    "convenience": "friction",
    "urgency": "friction",
}


class Footprint(Protocol):
    """Urma unui profil MiroFish in cont (``queen_agent.AvatarSegment`` o are)."""

    @property
    def key(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def share(self) -> float: ...

    @property
    def paid_clicks(self) -> int: ...

    @property
    def conversions(self) -> float: ...


class DecisionMode(BaseModel):
    """Kahneman: cum decide publicul care conteaza."""

    system: DecisionSystem
    #: Cota din public care decide deliberativ (profilurile de incredere si informare).
    deliberative_share: float
    label: str
    evidence: str
    #: Ce trebuie sa gaseasca in reclama ca sa decida.
    needs: list[str]


class ConversionBarrier(BaseModel):
    """Unde se rupe drumul de la click la cumparare."""

    kind: BarrierKind
    label: str
    evidence: str
    remedy: str


class PersuasionRoute(BaseModel):
    """ELM: pe ce ruta se convinge publicul."""

    route: RouteKind
    label: str
    cues: list[str]


class CognitiveProfile(BaseModel):
    """Psihologia cumparatorului, pentru directiva Reginei."""

    decision_mode: DecisionMode
    barrier: ConversionBarrier
    persuasion_route: PersuasionRoute
    #: Parghia psihologica pentru rescrieri.
    lever: str
    #: Profilul in doua-trei fraze - pentru client si ca fapt pentru LLM.
    summary: str


# --- 1. modul de decizie ----------------------------------------------------------

_MODE_LABELS: dict[DecisionSystem, str] = {
    "system_1": "Sistemul 1: decizie rapidă, pe intuiție",
    "system_2": "Sistemul 2: decizie cântărită, cu efort",
    "mixed": "mixt: o parte decide repede (Sistemul 1), o parte cântărește (Sistemul 2)",
}
_MODE_NEEDS: dict[DecisionSystem, list[str]] = {
    "system_1": [
        "dovada vizuală a rezultatului",
        "prețul spus direct",
        "un singur îndemn la acțiune",
    ],
    "system_2": [
        "specificații și detalii concrete",
        "comparația cu alternativele",
        "eliminarea riscului: garanții, recenzii, condiții clare",
    ],
    "mixed": [
        "un titlu scurt, pentru cine decide repede",
        "detaliile și garanțiile în text, pentru cine cântărește",
    ],
}
_MODE_SENTENCES: dict[DecisionSystem, str] = {
    "system_1": "Publicul tău decide repede, pe intuiție (Sistemul 1).",
    "system_2": "Publicul tău cântărește înainte să cumpere (Sistemul 2).",
    "mixed": (
        "Publicul tău e împărțit: o parte decide repede (Sistemul 1), o parte cântărește "
        "(Sistemul 2)."
    ),
}


def _names(profiles: Sequence[Footprint]) -> str:
    return ", ".join(f"«{profile.name}»" for profile in profiles)


def decision_mode(profiles: Sequence[Footprint]) -> DecisionMode:
    """Sistemul 1 sau 2, din cota profilurilor deliberative in ce aduce contul."""
    total = sum(profile.share for profile in profiles) or 1.0
    slow = [p for p in profiles if p.key in DELIBERATIVE_PROFILES and p.share > 0]
    fast = [p for p in profiles if p.key not in DELIBERATIVE_PROFILES and p.share > 0]
    deliberative = sum(p.share for p in slow) / total
    system: DecisionSystem
    if deliberative >= SYSTEM_2_FROM:
        system = "system_2"
    elif deliberative <= SYSTEM_1_UNTIL:
        system = "system_1"
    else:
        system = "mixed"
    parts = []
    if fast:
        parts.append(f"{percent(1 - deliberative)} decide repede ({_names(fast)})")
    if slow:
        parts.append(f"{percent(deliberative)} cântărește ({_names(slow)})")
    return DecisionMode(
        system=system,
        deliberative_share=round(deliberative, 4),
        label=_MODE_LABELS[system],
        evidence=f"Din publicul care contează, {' și '.join(parts)}.",
        needs=list(_MODE_NEEDS[system]),
    )


# --- 2. bariera de conversie ----------------------------------------------------

_BARRIER_LABELS: dict[BarrierKind, str] = {
    "friction": "fricțiune",
    "trust": "încredere",
    "perceived_value": "valoare percepută",
    "none": "nicio barieră clară",
    "unknown": "date insuficiente",
}
_BARRIER_WHY: dict[BarrierKind, str] = {
    "perceived_value": "Omul vede prețul înainte să vadă ce primește.",
    "trust": "Omul caută siguranță și nu o găsește destul de repede.",
    "friction": (
        "Omul vine hotărât să rezolve repede, iar drumul până la programare îl încurcă: prea "
        "mulți pași sau prea multe opțiuni."
    ),
}
_BARRIER_REMEDIES: dict[BarrierKind, str] = {
    "perceived_value": (
        "Arată întâi ce primește, ce include și ce evită, apoi prețul: valoarea ancorează prețul."
    ),
    "trust": "Pune autoritatea în față: recenzii reale, garanția scrisă, cine face lucrarea.",
    "friction": (
        "Taie opțiunile: un serviciu pe reclamă, un singur buton, un singur pas până la programare."
    ),
    "none": "Păstrează ce merge și testează variații mici.",
    "unknown": "Lasă campaniile să adune click-uri înainte de o concluzie.",
}
_BARRIER_SENTENCES: dict[BarrierKind, str] = {
    "perceived_value": "Îl oprește valoarea percepută: vede prețul înainte să vadă ce primește.",
    "trust": "Îl oprește încrederea: nu găsește destul de repede dovada că e pe mâini bune.",
    "friction": (
        "Îl oprește fricțiunea: prea mulți pași sau prea multe opțiuni între reclamă și programare."
    ),
    "none": "Conversia ține pe toate profilurile, fără o barieră anume.",
    "unknown": "Unde se rupe conversia nu se vede încă: sunt prea puține click-uri plătite.",
}


def _clicks(value: float) -> str:
    return "un click plătit" if value == 1 else count(value, "click-uri plătite")


def _conversions(value: float) -> str:
    return "nicio conversie" if value <= 0 else count(value, "conversii", "conversie")


def conversion_barrier(profiles: Sequence[Footprint]) -> ConversionBarrier:
    """Profilul de cumparator care pierde cele mai multe conversii fata de media contului."""
    clicks = sum(p.paid_clicks for p in profiles)
    conversions = sum(p.conversions for p in profiles)

    def _barrier(kind: BarrierKind, evidence: str) -> ConversionBarrier:
        return ConversionBarrier(
            kind=kind,
            label=_BARRIER_LABELS[kind],
            evidence=evidence,
            remedy=_BARRIER_REMEDIES[kind],
        )

    if clicks < MIN_PAID_CLICKS_FOR_BARRIER:
        return _barrier(
            "unknown",
            f"Doar {_clicks(clicks)} atribuite profilurilor, sub pragul de "
            f"{count(MIN_PAID_CLICKS_FOR_BARRIER, 'click-uri')} de la care se vede unde se rupe "
            "conversia.",
        )
    account_rate = conversions / clicks
    candidates: list[tuple[float, int, Footprint]] = []
    for order, profile in enumerate(profiles):
        if profile.key not in _BARRIER_BY_PROFILE:
            continue
        if profile.paid_clicks < MIN_PAID_CLICKS_FOR_BARRIER:
            continue
        profile_rate = profile.conversions / profile.paid_clicks
        if profile_rate > BARRIER_RATE_RATIO * account_rate:
            continue
        # Conversiile pierdute fata de media contului; fara nicio conversie in
        # cont, pierde cel mai mult profilul cu cele mai multe click-uri.
        lost = profile.paid_clicks * account_rate - profile.conversions
        candidates.append((lost if account_rate > 0 else profile.paid_clicks, -order, profile))

    if not candidates:
        return _barrier(
            "none",
            f"Niciun profil de cumpărător nu convertește mult sub media contului "
            f"({rate(account_rate)} din {_clicks(clicks)}).",
        )
    _, _, worst = max(candidates, key=lambda item: (item[0], item[1]))
    kind = _BARRIER_BY_PROFILE[worst.key]
    average = (
        f"sub media contului de {rate(account_rate)}"
        if account_rate > 0
        else "iar contul nu are încă nicio conversie pe căutările plătite"
    )
    profile_rate = worst.conversions / worst.paid_clicks
    detail = f" ({rate(profile_rate)})" if worst.conversions > 0 else ""
    return _barrier(
        kind,
        f"«{worst.name}» aduce {_clicks(worst.paid_clicks)} și "
        f"{_conversions(worst.conversions)}{detail}, {average}. {_BARRIER_WHY[kind]}",
    )


# --- 3. ruta de persuasiune -------------------------------------------------------

_ROUTES: dict[DecisionSystem, tuple[RouteKind, str, list[str]]] = {
    "system_1": (
        "peripheral",
        "Ruta periferică (ELM): convinge prin semnale rapide, nu prin argumente lungi",
        ["imaginea clară a rezultatului", "brandul vizibil", "dovada socială: recenzii, stele"],
    ),
    "system_2": (
        "central",
        "Ruta centrală (ELM): convinge prin argumente",
        ["argumente și cifre verificabile", "specificații și comparații", "garanții scrise"],
    ),
    "mixed": (
        "dual",
        "Ambele rute (ELM): titlul convinge repede, textul argumentează",
        ["titlu scurt, cu rezultatul", "argumentele și garanțiile în text"],
    ),
}
_ROUTE_PHRASES: dict[RouteKind, str] = {
    "peripheral": "ruta periferică: imagine, brand, recenzii",
    "central": "ruta centrală: argumente, cifre, garanții",
    "dual": "ambele rute: titlu rapid, argumente în text",
}
#: Parghia pentru texte: numele ei si ce inseamna concret.
_LEVERS: dict[DecisionSystem, tuple[str, str]] = {
    "system_1": ("aversiunea la pierdere", "ce pierde omul dacă mai amână"),
    "system_2": ("eliminarea riscului", "garanții, comparații, dovezi"),
    "mixed": (
        "aversiunea la pierdere în titlu și eliminarea riscului în text",
        "titlul arată ce pierde, textul de ce nu riscă",
    ),
}


#: Intr-un domeniu sensibil (sanatate, financiar, recrutare), nu aversiunea la pierdere:
#: frica impinge, dar nu e corect fata de omul care decide (garda fear_manipulation_risk).
_SAFE_LEVER = ("eliminarea riscului", "garanții, condiții clare, fără presiune")


def persuasion_route(mode: DecisionMode) -> PersuasionRoute:
    route, label, cues = _ROUTES[mode.system]
    return PersuasionRoute(route=route, label=label, cues=list(cues))


def cognitive_profile(
    profiles: Sequence[Footprint], *, sensitive: bool = False
) -> CognitiveProfile:
    """Profilul complet - functie pura, determinista."""
    mode = decision_mode(profiles)
    barrier = conversion_barrier(profiles)
    route = persuasion_route(mode)
    lever, meaning = _SAFE_LEVER if sensitive else _LEVERS[mode.system]
    summary = (
        f"{_MODE_SENTENCES[mode.system]} {_BARRIER_SENTENCES[barrier.kind]} Mesajul merge pe "
        f"{_ROUTE_PHRASES[route.route]}. Pârghia pentru texte e {lever} ({meaning})."
    )
    return CognitiveProfile(
        decision_mode=mode,
        barrier=barrier,
        persuasion_route=route,
        lever=f"{lever}: {meaning}",
        summary=summary,
    )


# --- reclamele: ce efort cer -------------------------------------------------------


def ad_demand(text: str, *, technical: bool) -> tuple[AdDemand, str]:
    """Ce sistem cere o reclama ca sa fie inteleasa, si de ce."""
    if technical:
        return "system_2", "termeni tehnici pe care trebuie să-i descifreze"
    words = len(tokenize(text))
    if words > LONG_AD_WORDS:
        return "system_2", f"{count(words, 'cuvinte')} de citit înainte de ofertă"
    return "system_1", ""


def ad_fit_note(mode: DecisionMode, headline: str, demand: AdDemand, why: str) -> str | None:
    """Nepotrivirea dintre cum decide publicul si ce efort ii cere reclama, sau ``None``."""
    if mode.system == "system_1" and demand == "system_2":
        return (
            f"{_MODE_SENTENCES['system_1']} Reclama «{headline}» îl pune să gândească "
            f"(Sistemul 2): {why}. Pierdem atenția."
        )
    if mode.system == "system_2" and demand == "system_1":
        return (
            f"{_MODE_SENTENCES['system_2']} Reclama «{headline}» e prea sumară pentru el: "
            "lipsesc detaliile și garanțiile pe care le caută."
        )
    return None
