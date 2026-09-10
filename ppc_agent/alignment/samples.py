"""Grupuri de anunturi de exemplu, generate cu modulul de copywriting.

Inlocuieste vechile texte hardcodate: copy-ul e produs de :class:`AdCopyGenerator`
cu ``MockLLMClient`` (determinist), din framework-urile emotionale din
``swipe_file.json``. Cuvantul cheie exact este fortat intr-un headline.

In productie, aceste seed-uri (keyword + USP + declansator) vin din Modulul 1
(cuvinte cheie) plus o decizie de strategie emotionala per grup.
"""

from __future__ import annotations

from ppc_agent.alignment.models import AdGroupInput
from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.llm import MockLLMClient

# ad_group_id, nume, cuvant cheie exact, USP, declansator emotional
_SEEDS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "ag_facturare_online",
        "Facturare online",
        "facturare online",
        "Emiti si trimiti facturi dintr-un loc, cu incasare automata prin card",
        "aida",
    ),
    (
        "ag_program_facturare",
        "Program facturare",
        "program facturare",
        "Program de facturare cu e-Factura inclusa, de la 29 lei pe luna",
        "fomo",
    ),
    (
        "ag_gestiune_stocuri",
        "Gestiune stocuri",
        "gestiune stocuri",
        "Vezi stocul real si valoarea marfii in timp real, fara Excel",
        "pas",
    ),
)


def sample_ad_groups() -> list[AdGroupInput]:
    """Genereaza grupurile de anunturi de exemplu (determinist)."""
    generator = AdCopyGenerator(MockLLMClient())
    groups: list[AdGroupInput] = []
    for ad_group_id, name, keyword, usp, trigger in _SEEDS:
        copy = generator.generate_emotional_copy(usp, keyword, trigger)
        groups.append(
            AdGroupInput(
                ad_group_id=ad_group_id,
                name=name,
                exact_match_keyword=keyword,
                headlines=[copy["headline_1"], copy["headline_2"]],
                descriptions=[copy["description"]],
            )
        )
    return groups
