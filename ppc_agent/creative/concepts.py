"""Sabloanele de concept post-Andromeda: structuri de reclama dovedite, pe bariera clientului.

Dupa Andromeda, creativul e targetarea: Meta citeste ce spune si ce arata reclama, apoi
o potriveste cu oameni care reactioneaza la acel mesaj. La buget mic nu se inventeaza
concepte noi; se testeaza structuri care au mers de zeci de ori (poveste de fondator,
noi-vs-ei, inainte/dupa), fiecare aleasa pentru bariera care tine clientul pe loc.

Un singur catalog, citit de toti agentii:

- **CMO** (``propensity.design_experiment``) aloca un sablon ipotezei, dupa bariera;
- **copywriterul** primeste pasii textului (``copy_beats``) si ce sa evite;
- **CCO** verifica daca imaginea sau video-ul respecta sablonul (``image_cues`` /
  ``video_beats``);
- **PPC** eticheteaza reclamele cu sablonul, ca diversitatea sa se poata masura.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

ConceptTemplate = Literal[
    "founder_story", "us_vs_them", "before_after", "testimonial", "product_demo"
]
CONCEPT_TEMPLATES: frozenset[str] = frozenset(get_args(ConceptTemplate))


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    """Ce inseamna un sablon pentru fiecare agent care il foloseste."""

    key: ConceptTemplate
    label: str
    #: Ce bariera rezolva si de ce.
    solves: str
    #: Pasii textului, in ordine (copywriterul).
    copy_beats: tuple[str, ...]
    #: Ce trebuie sa se vada intr-o imagine (CCO).
    image_cues: tuple[str, ...]
    #: Pasii unui video, cu secundele aproximative (CCO + productia).
    video_beats: tuple[str, ...]
    avoid: tuple[str, ...]


CONCEPTS: dict[ConceptTemplate, ConceptSpec] = {
    "founder_story": ConceptSpec(
        key="founder_story",
        label="Povestea fondatorului",
        solves="lipsa de încredere: un om real, cu nume și motiv, în locul unei firme anonime",
        copy_beats=(
            "cine sunt eu și ce fac, într-o frază",
            "momentul în care am văzut problema clientului",
            "ce fac altfel din cauza asta",
            "dovada: de câți ani, câți clienți, o garanție",
            "invitația la pasul următor",
        ),
        image_cues=(
            "fondatorul sau echipa reală, la locul de muncă, nu o fotografie de stoc",
            "numele sau rolul persoanei, scris pe imagine",
        ),
        video_beats=(
            "0-3 s: fondatorul în cadru, numește problema clientului",
            "3-15 s: de ce a pornit afacerea, ce face altfel",
            "15-25 s: dovada (ani, clienți, garanție), arătată nu doar spusă",
            "final: ce să facă privitorul acum",
        ),
        avoid=("actori sau fotografii de stoc", "povești fără legătură cu problema clientului"),
    ),
    "us_vs_them": ConceptSpec(
        key="us_vs_them",
        label="Noi vs. ei",
        solves=(
            "prea multe opțiuni sau un preț greu de judecat: o comparație simplă face "
            "alegerea în locul clientului"
        ),
        copy_beats=(
            "alternativa obișnuită (fără nume de concurenți) și ce o face proastă",
            "ce facem noi diferit, pe două-trei criterii care contează pentru client",
            "concluzia, într-o frază",
            "pasul următor",
        ),
        image_cues=(
            "două coloane sau două jumătăți clar separate: alternativa vs. noi",
            "maximum trei criterii, cu bifă/X sau cifre",
        ),
        video_beats=(
            "0-3 s: alternativa obișnuită și problema ei, arătată",
            "3-15 s: aceeași situație cu noi, pe aceleași criterii",
            "final: concluzia și pasul următor",
        ),
        avoid=("numele sau logo-ul unui concurent", "mai mult de trei criterii"),
    ),
    "before_after": ConceptSpec(
        key="before_after",
        label="Înainte / după",
        solves=(
            "treaba pe care o vrea făcută clientul (functional job): arată rezultatul, nu procesul"
        ),
        copy_beats=(
            "situația de dinainte, în cuvintele clientului",
            "ce s-a schimbat și în cât timp",
            "cum (pe scurt) și ce trebuie să facă el",
            "pasul următor",
        ),
        image_cues=(
            "două stări vizibile ale aceluiași lucru: înainte și după",
            "etichete «înainte» / «după» sau o săgeată clară între ele",
        ),
        video_beats=(
            "0-3 s: starea de dinainte, recognoscibilă pentru client",
            "3-15 s: transformarea sau rezultatul, arătat",
            "final: ce să facă privitorul ca să ajungă la «după»",
        ),
        avoid=(
            "rezultate promise fără dovadă",
            "în sănătate: fotografii medicale explicite sau promisiuni de vindecare",
        ),
    ),
    "testimonial": ConceptSpec(
        key="testimonial",
        label="Mărturia unui client",
        solves="riscul perceput: un client ca el spune ce a primit, deci riscul pare mic",
        copy_beats=(
            "citatul clientului, cu situația lui de dinainte",
            "rezultatul concret pe care l-a primit",
            "cine e (prenume, oraș, ce a cumpărat)",
            "pasul următor",
        ),
        image_cues=(
            "un client real sau recenzia lui (stele, nume), lizibilă",
            "citatul scris mare, nu ascuns",
        ),
        video_beats=(
            "0-3 s: clientul spune rezultatul sau problema de la care a pornit",
            "3-20 s: experiența lui, în cuvintele lui",
            "final: pasul următor, spus sau scris",
        ),
        avoid=("recenzii inventate sau actori prezentați drept clienți",),
    ),
    "product_demo": ConceptSpec(
        key="product_demo",
        label="Demonstrație",
        solves="fricțiunea: arată cât de simplu e drumul până la rezultat",
        copy_beats=(
            "problema, într-o frază",
            "pașii, numerotați (maximum trei)",
            "rezultatul",
            "pasul următor",
        ),
        image_cues=(
            "produsul sau serviciul în folosire, nu doar ambalajul",
            "pașii sau rezultatul, vizibili dintr-o privire",
        ),
        video_beats=(
            "0-3 s: produsul în acțiune, pe problema clientului",
            "3-20 s: pașii, arătați în ordine",
            "final: rezultatul și pasul următor",
        ),
        avoid=("demonstrații lungi, fără rezultat în primele secunde",),
    ),
}


def concept_brief(key: ConceptTemplate) -> dict[str, object]:
    """Ce primeste copywriterul: sablonul, ce rezolva, pasii textului si ce sa evite."""
    spec = CONCEPTS[key]
    return {
        "template": spec.key,
        "label": spec.label,
        "solves": spec.solves,
        "copy_beats": list(spec.copy_beats),
        "avoid": list(spec.avoid),
    }


def concept_label(key: str | None) -> str:
    """Eticheta sablonului, pentru oameni; ``""`` cand nu exista."""
    if not key:
        return ""
    spec = CONCEPTS.get(key)  # type: ignore[call-overload]
    return spec.label if spec is not None else key
