"""Reguli post-Andromeda pentru portofoliul de reclame al unei lansari Meta.

Dupa Andromeda, creativul e parametrul de targetare: Meta transcrie audio-ul si
citeste textul din cadru, apoi potriveste mesajul cu oameni care reactioneaza la el.
De aici trei reguli pe care o lansare le poate incalca fara sa faca nicio greseala
de structura (campanie unica, targetare larga - acelea sunt deja corecte):

1. **Diversitate reala, nu variatii.** Reclame cu acelasi mesaj si alta imagine sunt
   grupate de Meta ca una singura (creative similarity) si lovesc aceiasi oameni.
   Diferenta conteaza la persoana, unghi si oferta - formatul e partea cu cel mai
   mic efect.
2. **Hook specific.** Un inceput generic ("Hey, trebuie sa vezi asta") nu da
   algoritmului nicio problema sau persoana de care sa se agate.
3. **Formate diferite.** Imaginea si video-ul intra in licitatii diferite; doar imagini
   inseamna ca o parte din public nu vede niciodata reclama.
4. **Numar de reclame pe masura bugetului.** Mai multe reclame decat poate hrani
   bugetul raman nediagnosticate (``budget_strategy.recommend_arm_capacity``);
   mai putine decat poate hrani inseamna diversitate lasata pe masa.

Functiile sunt pure: iau reclamele si returneaza constatari, fara retea si fara
stare. Doar brief-ul de lansare decide ce arata omului care aproba.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol

from ppc_agent.texttools import normalize, tokenize

#: De la cat de mare e suprapunerea de cuvinte, doua reclame se considera acelasi mesaj.
SIMILARITY_THRESHOLD = 0.6

#: Inceputuri care nu numesc nicio problema, persoana sau oferta (comparate pe
#: jetoane normalizate, fara diacritice).
_GENERIC_OPENERS: tuple[tuple[str, ...], ...] = (
    ("hey",),
    ("hei",),
    ("salut",),
    ("buna",),
    ("check", "this", "out"),
    ("uite",),
    ("uita", "te"),
    ("nu", "o", "sa", "crezi"),
    ("you", "have", "to", "see"),
)


class AdText(Protocol):
    @property
    def headline(self) -> str: ...
    @property
    def primary_text(self) -> str: ...
    @property
    def angle(self) -> str: ...
    @property
    def format(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PortfolioFindings:
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _label(index: int) -> str:
    return f"reclama {index + 1}"


def is_generic_hook(text: str) -> bool:
    """Textul incepe cu o formula care nu numeste problema sau persoana."""
    tokens = tokenize(text)
    return any(tuple(tokens[: len(opener)]) == opener for opener in _GENERIC_OPENERS)


def similar_pairs(ads: Sequence[AdText]) -> list[tuple[int, int, float]]:
    """Perechile de reclame cu acelasi mesaj, dupa suprapunerea cuvintelor."""
    tokens = [set(tokenize(f"{ad.headline} {ad.primary_text}")) for ad in ads]
    found = []
    for left, right in combinations(range(len(ads)), 2):
        score = _jaccard(tokens[left], tokens[right])
        if score >= SIMILARITY_THRESHOLD:
            found.append((left, right, round(score, 2)))
    return found


def portfolio_findings(
    ads: Sequence[AdText], *, max_concurrent_arms: int | None = None
) -> PortfolioFindings:
    """Constatarile post-Andromeda pentru reclamele unei lansari.

    Args:
        ads: Reclamele lansarii, prima fiind cea principala.
        max_concurrent_arms: Cate variante hraneste bugetul
            (``ArmCapacityAdvice.recommended_max_concurrent_arms``); ``None`` cand
            CPA-ul tinta nu e cunoscut si capacitatea nu se poate calcula.
    """
    result = PortfolioFindings()

    for left, right, score in similar_pairs(ads):
        result.warnings.append(
            f"{_label(left)} si {_label(right)} spun aproape acelasi lucru "
            f"(suprapunere {score:.0%}). Meta le grupeaza ca pe o singura reclama si le "
            "arata acelorasi oameni; schimba persoana, unghiul sau oferta, nu doar imaginea."
        )

    seen_angles: dict[str, int] = {}
    for index, ad in enumerate(ads):
        angle = normalize(ad.angle).strip()
        if not angle:
            continue
        if angle in seen_angles:
            result.warnings.append(
                f"{_label(seen_angles[angle])} si {_label(index)} au acelasi unghi "
                f"('{ad.angle.strip()}'). Unghiul e cel mai puternic factor de diversitate."
            )
        else:
            seen_angles[angle] = index

    for index, ad in enumerate(ads):
        if is_generic_hook(ad.primary_text) or is_generic_hook(ad.headline):
            result.warnings.append(
                f"{_label(index)} incepe cu o formula generica. Dupa Andromeda, inceputul "
                "e targetarea: numeste problema sau persoana (ex. durerea concreta, rolul, "
                "situatia), altfel algoritmul nu are de ce sa se agate."
            )

    if len(ads) >= 2 and all(ad.format == "image" for ad in ads):
        result.suggestions.append(
            "toate reclamele sunt imagini. Imaginea si video-ul intra in licitatii diferite: "
            "un video (chiar simplu, filmat cu telefonul) ajunge la oameni pe care imaginile "
            "nu-i prind."
        )

    if max_concurrent_arms is not None:
        count = len(ads)
        if count > max_concurrent_arms:
            result.warnings.append(
                f"{count} reclame, dar bugetul hraneste cel mult {max_concurrent_arms}: "
                "restul raman fara suficienta cheltuiala pentru un verdict. Lanseaza mai "
                "putine, sau creste bugetul."
            )
        elif count == 1 and max_concurrent_arms >= 2:
            result.suggestions.append(
                f"o singura reclama, desi bugetul hraneste pana la {max_concurrent_arms}. "
                "Post-Andromeda, Meta cere diversitate: adauga reclame cu persoane sau "
                "unghiuri diferite in acelasi ad set."
            )

    return result
