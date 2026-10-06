"""CMO-ul (Regina): intentia de cumparare, bariera dominanta si experimentul care o testeaza.

Formula conceptuala de propensitate, calculata determinist:

    P(actiune) = (Relevanta + Valoare + Incredere) - (Risc + Frictiune)

Fiecare factor e pe 0-10, pornind de la 5 (neutru = nu stim nimic) si se misca doar cu o
dovada, scrisa in ``evidence``:

- **Relevanta**: cat le vorbesc reclamele live clientului ideal (alinierea MiroFish);
- **Valoare** si **Incredere**: bariera masurata in cont (``cognitive.py``) si grijile
  spuse de client in interviul JTBD (``avatar_builder.py``);
- **Risc**: grijile despre rezultat, costul schimbarii; o garantie il scade;
- **Frictiune**: bariera masurata, grijile despre timp si drum, peste 3 pachete
  (choice overload).

Bariera dominanta e factorul cel mai departe de neutru, in directia rea. Pentru ea,
CMO-ul nu arunca texte de reclama: propune UN experiment, cu ipoteza falsificabila -
varianta, controlul, metrica, pragul de succes, esantionul si ce o infirma. Experimentul
primeste si un sablon de concept post-Andromeda (``ppc_agent/creative/concepts.py``): o
structura de reclama dovedita pentru bariera respectiva, pe care o urmeaza copywriterul,
o verifica CCO-ul si o eticheteaza PPC-ul:

- lipsa de incredere -> povestea fondatorului;
- prea multe pachete (choice overload) sau pretul greu de judecat -> noi vs. ei;
- treaba clientului (functional job) cunoscuta, pe risc sau relevanta -> inainte/dupa;
- risc sau relevanta fara functional job -> marturia unui client;
- fricțiune fara choice overload -> demonstratie.

Garda etica ``fear_manipulation_risk``: in domeniile sensibile (sanatate, financiar,
recrutare - ca la CCO), Regina nu foloseste frica: declansatorii de frica nu ajung la
copywriter, iar textele scrise de model cu ton alarmist sunt respinse.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ppc_agent.creative.concepts import CONCEPTS, ConceptTemplate
from ppc_agent.texttools import normalize, tokenize
from ppc_agent_server.services.avatar_builder import CustomerAvatar, OfferFacts
from ppc_agent_server.services.cognitive import BarrierKind

Barrier = Literal[
    "lack_of_trust", "price_uncertainty", "perceived_risk", "friction", "low_relevance"
]
SensitiveDomain = Literal["health", "finance", "recruitment"]

#: Neutrul fiecarui factor: fara dovada, nu stim nimic.
NEUTRAL = 5
#: Cu cat bate varianta controlul ca ipoteza sa stea in picioare (relativ, la conversie).
MIN_LIFT_PCT = 15
#: Esantionul minim al unui experiment, pe varianta.
MIN_CLICKS_PER_ARM = 100
MIN_TEST_DAYS = 14
#: Peste atatea pachete, alegerea se amana (Iyengar).
MAX_OPTIONS = 3

BARRIER_LABELS: dict[Barrier, str] = {
    "lack_of_trust": "lipsa de încredere",
    "price_uncertainty": "incertitudinea prețului",
    "perceived_risk": "riscul perceput",
    "friction": "fricțiunea",
    "low_relevance": "relevanța mică a mesajului",
}
SENSITIVE_LABELS: dict[SensitiveDomain, str] = {
    "health": "sănătate",
    "finance": "financiar",
    "recruitment": "recrutare",
}

# ponytail: cuvinte cheie pe raspunsurile clientului si pe cautari; o intrebare Jev
# (ca domeniul la CCO) le-ar prinde si pe cele spuse altfel, daca devine important.
_ANXIETY_MARKERS: dict[str, tuple[str, ...]] = {
    "price": ("pret", "scump", "cost", "bani", "tarif", "buget", "plat"),
    "trust": ("incredere", "teapa", "pacal", "serios", "recenzi", "necunoscut", "cine sunt"),
    "risk": (
        "iese", "nu merge", "risc", "rezultat", "calitat", "esue", "gresit", "stric", "dezamag",
    ),
    "friction": ("timp", "drum", "departe", "complicat", "astept", "programar", "birocra"),
}
_SENSITIVE_MARKERS: dict[SensitiveDomain, tuple[str, ...]] = {
    "health": (
        "clinic", "medic", "stomatolog", "dentist", "tratament", "boal", "sanatat", "terapi",
        "farmac", "spital", "diagnost", "psiholog", "kineto", "fizioterap", "dermatolog",
        "oftalmolog", "ortoped",
    ),
    "finance": (
        "credit", "imprumut", "ipotec", "asigurar", "investit", "leasing", "datori", "pensie",
        "trading", "crypto",
    ),
    "recruitment": ("angajam", "angajare", "recrut", "job", "salariu", "cariera"),
}
#: Tonul alarmist (pe text normalizat: fara diacritice, litere mici).
_FEAR = re.compile(
    r"\b(?:risti|pericol\w*|alarm\w*|mori|moarte|deces\w*|fatal\w*|prea tarziu|"
    r"ultima (?:ta )?sansa|nu mai ai timp|te costa viata|distrug\w*|dezastr\w*|catastrof\w*|"
    r"panic\w*|infricos\w*|ingrozit\w*|grav[ae]?|complicati\w*|pierzi tot|"
    r"ai putea pierde tot|faliment\w*|executare silita|concediat\w*)\b"
)
#: Declansatorii copywriterului care duc la framework-urile de frica (PAS, FOMO).
FEAR_TRIGGERS = frozenset({"frica", "teama", "risc", "urgenta", "pericol", "pierdere", "fomo"})
#: Ce primeste copywriterul in locul lor, intr-un domeniu sensibil.
SAFE_TRIGGER = "beneficiu"


class PropensityScore(BaseModel):
    """P(actiune) si factorii ei, fiecare pe 0-10 (5 = neutru)."""

    relevance: int = Field(ge=0, le=10)
    value: int = Field(ge=0, le=10)
    trust: int = Field(ge=0, le=10)
    risk: int = Field(ge=0, le=10)
    friction: int = Field(ge=0, le=10)
    #: (Relevanta + Valoare + Incredere) - (Risc + Frictiune), intre -20 si 30.
    p_action: int
    #: Factorul cel mai departe de neutru, in directia rea; ``None`` = nicio dovada.
    dominant_barrier: Barrier | None
    evidence: list[str]


class Experiment(BaseModel):
    """Un test A/B cu ipoteza falsificabila - nu un text aruncat la intamplare."""

    barrier: Barrier
    hypothesis: str
    #: Varianta (ce se schimba).
    change: str
    control: str
    metric: str
    success_criterion: str
    min_sample: str
    #: Ce rezultat infirma ipoteza.
    falsified_if: str
    #: Structura de reclama post-Andromeda aleasa pentru bariera (``creative/concepts.py``).
    concept_template: ConceptTemplate
    #: De ce acest sablon, in cuvintele CMO-ului.
    concept_reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _concept_for_saved_hypotheses(cls, data: object) -> object:
        """Ipotezele publicate inainte de sabloane primesc sablonul implicit al barierei."""
        if isinstance(data, dict) and not data.get("concept_template"):
            barrier = data.get("barrier")
            if barrier in DEFAULT_CONCEPT:
                return {**data, "concept_template": DEFAULT_CONCEPT[barrier]}
        return data


#: Sablonul fiecarei bariere cand nu stim nimic in plus despre client sau oferta.
DEFAULT_CONCEPT: dict[str, ConceptTemplate] = {
    "lack_of_trust": "founder_story",
    "price_uncertainty": "us_vs_them",
    "perceived_risk": "testimonial",
    "friction": "product_demo",
    "low_relevance": "testimonial",
}


def choose_concept(
    barrier: Barrier, avatar: CustomerAvatar | None, offer: OfferFacts | None
) -> tuple[ConceptTemplate, str]:
    """Sablonul de concept pentru bariera, cu motivul (determinist, fara model)."""
    job = avatar.functional_job if avatar is not None else None
    overloaded = offer is not None and offer.options is not None and offer.options > MAX_OPTIONS
    if barrier == "lack_of_trust":
        return "founder_story", "un om real, cu nume și motiv, construiește încredere mai repede"
    if barrier == "friction" and overloaded:
        assert offer is not None and offer.options is not None
        return "us_vs_them", (
            f"{offer.options} pachete de ales (choice overload): o comparație simplă alege "
            "în locul clientului"
        )
    if barrier == "price_uncertainty":
        return "us_vs_them", "comparația cu alternativa obișnuită arată ce primește pe bani"
    if barrier in ("perceived_risk", "low_relevance") and job:
        return "before_after", f"arată treaba făcută («{job}»), nu procesul"
    if barrier in ("perceived_risk", "low_relevance"):
        return "testimonial", "un client ca el spune ce a primit"
    return "product_demo", "arată cât de scurt e drumul până la rezultat"


def _mentions(texts: Iterable[str], markers: Sequence[str]) -> str | None:
    """Primul text care contine unul dintre markeri (pe forma normalizata)."""
    return next((text for text in texts if any(m in normalize(text) for m in markers)), None)


def sensitive_domain(texts: Iterable[str]) -> SensitiveDomain | None:
    """Domeniul sensibil al afacerii, din brand, cautari si raspunsurile clientului."""
    tokens = [token for text in texts for token in tokenize(text)]
    for domain, markers in _SENSITIVE_MARKERS.items():
        if any(token.startswith(markers) for token in tokens):
            return domain
    return None


def fear_manipulation_risk(text: str) -> list[str]:
    """Formularile alarmiste dintr-un text (gol = fara risc)."""
    return list(dict.fromkeys(match.group() for match in _FEAR.finditer(normalize(text))))


def safe_trigger(trigger: str, domain: SensitiveDomain | None) -> str:
    """Declansatorul pentru copywriter: fara frica intr-un domeniu sensibil."""
    return SAFE_TRIGGER if domain is not None and normalize(trigger) in FEAR_TRIGGERS else trigger


def _clamp(value: int) -> int:
    return max(0, min(10, value))


def score_propensity(
    *,
    avatar: CustomerAvatar | None,
    offer: OfferFacts | None,
    measured_barrier: BarrierKind | None,
    alignment: Sequence[float],
) -> PropensityScore:
    """P(actiune) din ce se stie: alinierea reclamelor, bariera din cont, interviul JTBD."""
    evidence: list[str] = []
    worries = avatar.anxieties if avatar is not None else []
    relevance = NEUTRAL
    if alignment:
        relevance = round(10 * sum(alignment) / len(alignment))
        evidence.append(
            f"Relevanța {relevance}/10: atât le vorbesc reclamele live clientului ideal."
        )
    value = trust = risk = friction = NEUTRAL
    if measured_barrier == "perceived_value":
        value -= 3
        evidence.append("Valoarea -3: în cont, cine caută prețul convertește mult sub medie.")
    if measured_barrier == "trust":
        trust -= 3
        evidence.append("Încrederea -3: în cont, cine caută garanții convertește mult sub medie.")
    if measured_barrier == "friction":
        friction += 3
        evidence.append("Fricțiunea +3: în cont, cine vrea repede convertește mult sub medie.")
    if said := _mentions(worries, _ANXIETY_MARKERS["price"]):
        value -= 2
        evidence.append(f"Valoarea -2: clientul ezită din cauza prețului («{said}»).")
    if said := _mentions(worries, _ANXIETY_MARKERS["trust"]):
        trust -= 2
        evidence.append(f"Încrederea -2: clientul nu are încă încredere («{said}»).")
    if said := _mentions(worries, _ANXIETY_MARKERS["risk"]):
        risk += 2
        evidence.append(f"Riscul +2: clientul se teme de rezultat («{said}»).")
    if said := _mentions(worries, _ANXIETY_MARKERS["friction"]):
        friction += 2
        evidence.append(f"Fricțiunea +2: drumul până la cumpărare îl costă («{said}»).")
    if avatar is not None and avatar.switching_cost:
        risk += 1
        evidence.append(f"Riscul +1: schimbarea îl costă («{avatar.switching_cost}»).")
    if offer is not None and offer.risk_reversal:
        risk -= 2
        evidence.append(f"Riscul -2: oferta are deja o garanție («{offer.risk_reversal}»).")
    if offer is not None and offer.options is not None and offer.options > MAX_OPTIONS:
        friction += 2
        evidence.append(
            f"Fricțiunea +2: {offer.options} pachete de ales, peste {MAX_OPTIONS} "
            "(choice overload)."
        )
    relevance, value, trust = _clamp(relevance), _clamp(value), _clamp(trust)
    risk, friction = _clamp(risk), _clamp(friction)
    # Cat de departe de neutru, in directia rea; la egalitate, ordinea din Barrier.
    gaps: dict[Barrier, int] = {
        "lack_of_trust": NEUTRAL - trust,
        "price_uncertainty": NEUTRAL - value,
        "perceived_risk": risk - NEUTRAL,
        "friction": friction - NEUTRAL,
        "low_relevance": NEUTRAL - relevance,
    }
    worst = max(gaps, key=lambda barrier: gaps[barrier])
    return PropensityScore(
        relevance=relevance,
        value=value,
        trust=trust,
        risk=risk,
        friction=friction,
        p_action=(relevance + value + trust) - (risk + friction),
        dominant_barrier=worst if gaps[worst] > 0 else None,
        evidence=evidence,
    )


#: Pe bariera: varianta testata si mecanismul prin care ar creste conversia.
_PLAYBOOK: dict[Barrier, tuple[str, str]] = {
    "lack_of_trust": (
        "punem dovada în prim-plan: recenzii reale, cine face lucrarea, garanția scrisă",
        "omul vede repede că e pe mâini bune",
    ),
    "price_uncertainty": (
        "spunem prețul (sau «de la ... lei») și ce include, chiar în reclamă",
        "omul nu mai pleacă să afle cât costă",
    ),
    "perceived_risk": (
        "spunem în titlu inversarea riscului: garanția, o primă consultație sau un audit gratuit",
        "omul nu mai riscă nimic ca să încerce",
    ),
    "friction": (
        "lăsăm un singur pas: un buton, un formular scurt sau programarea directă",
        "drumul până la cerere e mai scurt",
    ),
    "low_relevance": (
        "scriem titlul pe situația clientului ideal, cu cuvintele lui",
        "omul se recunoaște în reclamă",
    ),
}


def design_experiment(
    score: PropensityScore,
    avatar: CustomerAvatar | None,
    offer: OfferFacts | None = None,
) -> Experiment | None:
    """Experimentul pe bariera dominanta; ``None`` fara bariera (nimic de testat inca)."""
    barrier = score.dominant_barrier
    if barrier is None:
        return None
    concept, reason = choose_concept(barrier, avatar, offer)
    change, mechanism = _PLAYBOOK[barrier]
    if barrier == "low_relevance" and avatar is not None and avatar.customer_situation:
        change += f" («{avatar.customer_situation}»)"
    label = BARRIER_LABELS[barrier]
    return Experiment(
        barrier=barrier,
        hypothesis=(
            f"Dacă {change}, rata de conversie crește cu cel puțin {MIN_LIFT_PCT}% față de "
            f"reclama actuală, pentru că {mechanism}."
        ),
        change=change[:1].upper() + change[1:],
        control="Reclama actuală, neschimbată, pe același buget și aceeași audiență.",
        metric="rata de conversie (conversii / click-uri)",
        success_criterion=(
            f"varianta bate controlul cu cel puțin {MIN_LIFT_PCT}% la rata de conversie"
        ),
        min_sample=(
            f"cel puțin {MIN_CLICKS_PER_ARM} de click-uri pe fiecare variantă și "
            f"{MIN_TEST_DAYS} zile"
        ),
        falsified_if=(
            f"varianta nu bate controlul cu {MIN_LIFT_PCT}% după eșantion: atunci {label} nu "
            "era bariera, iar următorul test merge pe a doua barieră"
        ),
        concept_template=concept,
        concept_reason=reason,
    )


def experiment_line(experiment: Experiment) -> str:
    """Experimentul intr-o fraza, pentru client si pentru consiliu."""
    return (
        f"Bariera dominantă e {BARRIER_LABELS[experiment.barrier]}. Experimentul: "
        f"{experiment.hypothesis} Conceptul reclamei: "
        f"{CONCEPTS[experiment.concept_template].label}. Testăm pe {experiment.min_sample}; "
        f"ipoteza cade dacă {experiment.falsified_if}."
    )
