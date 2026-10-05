"""Avatar Builder: clientul ideal in "Jobs to Be Done", din raspunsurile clientului.

Inainte de prima campanie (dupa costuri si zona, ``client_intake.py``), consiliul
intreaba in chat ce il aduce pe un om la afacere - nu cine e (varsta si genul nu se
deduc din cautari, vezi ``queen_agent``), ci ce treaba vrea sa rezolve (Christensen):

- situatia in care ajunge sa caute si progresul pe care il vrea;
- treaba functionala, emotionala si sociala;
- ce il face sa ezite (``anxieties``) si ce il costa sa schimbe (``switching_cost``).

Profilul e scris cu cuvintele clientului - nimic generat, nimic ghicit: un "nu stiu"
lasa campul gol. Intra in directiva Reginei (``BrandSignals.customer_avatar``), deci il
vad toti cei care o primesc: CMO-ul (Regina), consiliul, CPO-ul; CCO-ul il primeste la
evaluarea creativelor.

Tot aici, doua fapte despre oferta, pentru arhitectura alegerii a CPO-ului: cate
pachete vede un client si ce garantie primeste (inversarea riscului).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: Cat pastram dintr-un raspuns (un rand de chat, nu un eseu).
MAX_ANSWER_CHARS = 300
#: Cate griji distincte tinem minte.
MAX_ANXIETIES = 5

_Answer = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ANSWER_CHARS)
]


class CustomerAvatar(BaseModel):
    """Clientul ideal in Jobs to Be Done. ``null`` / lista goala = clientul n-a stiut."""

    model_config = ConfigDict(title="CustomerAvatar")

    customer_situation: _Answer | None = Field(
        default=None,
        description="Ce se întâmplă în viața clientului chiar înainte să caute: momentul "
        "care declanșează cumpărarea.",
    )
    desired_progress: _Answer | None = Field(
        default=None, description="Ce vrea să fie diferit în viața lui după aceea."
    )
    functional_job: _Answer | None = Field(
        default=None, description="Treaba concretă pe care o rezolvă cu afacerea."
    )
    emotional_job: _Answer | None = Field(default=None, description="Cum vrea să se simtă.")
    social_job: _Answer | None = Field(
        default=None, description="Cum vrea să fie văzut de ceilalți."
    )
    anxieties: list[_Answer] = Field(
        default_factory=list,
        max_length=MAX_ANXIETIES,
        description="Ce îl face să ezite înainte să cumpere (prețul, încrederea, riscul).",
    )
    switching_cost: _Answer | None = Field(
        default=None,
        description="Ce folosește acum în loc și ce îl costă să schimbe: bani, timp, obișnuință.",
    )


class OfferFacts(BaseModel):
    """Oferta, cum o vede un client: pentru arhitectura alegerii (CPO)."""

    #: Cate pachete sau variante de pret vede; ``None`` = nu stim.
    options: int | None = Field(default=None, ge=1, le=100)
    #: Garantia sau proba fara risc; ``""`` = niciuna, ``None`` = nu stim.
    risk_reversal: str | None = Field(default=None, max_length=MAX_ANSWER_CHARS)


#: Ordinea intrebarilor din chat: intai situatia (de acolo pleaca tot), oferta la final.
AVATAR_KEYS: tuple[str, ...] = (
    "customer_situation",
    "functional_job",
    "desired_progress",
    "emotional_job",
    "social_job",
    "anxieties",
    "switching_cost",
)
OFFER_KEYS: tuple[str, ...] = ("offer_options", "risk_reversal")
PROFILE_KEYS: tuple[str, ...] = AVATAR_KEYS + OFFER_KEYS

#: Intrebarea, de ce o pune consiliul si un exemplu de raspuns - pe cheie.
QUESTIONS: dict[str, tuple[str, str, str]] = {
    "customer_situation": (
        "Ce se întâmplă în viața clientului tău chiar înainte să te caute?",
        "Momentul acela spune reclamei cui și când să vorbească.",
        "«i s-a stricat mașina și pleacă în concediu peste o săptămână»",
    ),
    "functional_job": (
        "Ce treabă concretă vrea să rezolve cu tine?",
        "Asta cumpără de fapt: nu serviciul, ci treaba făcută.",
        "«mașina reparată până vineri»",
    ),
    "desired_progress": (
        "Ce vrea să fie diferit în viața lui după aceea?",
        "Reclamele care vând progresul convertesc mai bine decât cele care descriu serviciul.",
        "«să plece liniștit la drum»",
    ),
    "emotional_job": (
        "Cum vrea să se simtă?",
        "Emoția decide tonul reclamei.",
        "«liniștit», «în siguranță», «mândru»",
    ),
    "social_job": (
        "Cum vrea să fie văzut de ceilalți (familie, colegi, clienții lui)?",
        "Ce spun ceilalți cântărește la decizie, mai ales la achizițiile mari.",
        "«un părinte care are grijă de ai lui», sau «nu contează»",
    ),
    "anxieties": (
        "Ce îl face să ezite înainte să cumpere de la tine?",
        "Bariera cea mai mare decide ce testăm primul în reclame.",
        "«prețul, și că nu știe dacă lucrarea iese bine»",
    ),
    "switching_cost": (
        "Ce folosește acum în locul tău și ce îl costă să schimbe (bani, timp, obișnuință)?",
        "Cu cât îl costă mai mult să schimbe, cu atât reclama trebuie să-i scadă riscul.",
        "«merge la service-ul de lângă bloc; i-ar fi greu să caute altul»",
    ),
    "offer_options": (
        "Câte pachete sau variante de preț vede un client la tine?",
        "Peste 3 variante, oamenii amână alegerea (choice overload).",
        "«3», sau «unul singur»",
    ),
    "risk_reversal": (
        "Oferi o garanție sau o primă probă fără risc (consultație, audit, retur gratuit)? Care?",
        "O garanție scade riscul pe care îl simte clientul înainte să cumpere.",
        "«garanție 12 luni», sau «nu»",
    ),
}

_LABELS = {
    "customer_situation": "situația",
    "functional_job": "treaba concretă",
    "desired_progress": "progresul dorit",
    "emotional_job": "cum vrea să se simtă",
    "social_job": "cum vrea să fie văzut",
    "switching_cost": "costul schimbării",
}


def profile_missing(answers: Mapping[str, Any] | None) -> str | None:
    """Prima intrebare fara raspuns ("nu stiu" e un raspuns); ``None`` = profil complet."""
    return next((key for key in PROFILE_KEYS if key not in (answers or {})), None)


def avatar_from_answers(answers: Mapping[str, Any] | None) -> CustomerAvatar | None:
    """Profilul din raspunsurile salvate; ``None`` cand clientul n-a raspuns la nimic."""
    given = {key: value for key, value in (answers or {}).items() if key in AVATAR_KEYS}
    if not given or not any(given.values()):
        return None
    if given.get("anxieties") is None:
        given.pop("anxieties", None)
    return CustomerAvatar.model_validate(given)


def offer_from_answers(answers: Mapping[str, Any] | None) -> OfferFacts | None:
    """Oferta din raspunsurile salvate; ``None`` cand nu s-a intrebat inca."""
    if not answers or not any(key in answers for key in OFFER_KEYS):
        return None
    return OfferFacts(
        options=answers.get("offer_options"), risk_reversal=answers.get("risk_reversal")
    )


def avatar_texts(avatar: CustomerAvatar | None) -> list[str]:
    """Tot ce a scris clientul despre clientul ideal (pentru clasificari pe cuvinte)."""
    if avatar is None:
        return []
    single = [getattr(avatar, key) for key in _LABELS]
    return [text for text in [*single, *avatar.anxieties] if text]


def avatar_facts(avatar: CustomerAvatar) -> str:
    """Profilul intr-o fraza, cu cuvintele clientului - fapt pentru agenti si pentru chat."""
    parts = [
        f"{label}: «{text}»"
        for key, label in _LABELS.items()
        if key != "switching_cost" and (text := getattr(avatar, key))
    ]
    if avatar.anxieties:
        parts.append("ce îl face să ezite: " + ", ".join(f"«{a}»" for a in avatar.anxieties))
    if avatar.switching_cost:
        parts.append(f"costul schimbării: «{avatar.switching_cost}»")
    return "Clientul ideal, în cuvintele afacerii (Jobs to Be Done) - " + "; ".join(parts) + "."
