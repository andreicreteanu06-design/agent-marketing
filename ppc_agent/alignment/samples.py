"""Copy de anunt de exemplu — stand-in pentru iesirea unui LLM de creatie.

In productie, ``AdGroupInput`` vine dintr-un pas separat de generare de copy.
Aici sunt trei grupuri fixe, alese sa arate un raport Quality Score variat.
"""

from __future__ import annotations

from ppc_agent.alignment.models import AdGroupInput

_SAMPLE_AD_GROUPS: tuple[AdGroupInput, ...] = (
    AdGroupInput(
        ad_group_id="ag_facturare_online",
        name="Facturare online",
        exact_match_keyword="facturare online",
        headlines=[
            "Facturare online fara batai de cap",
            "Incepe facturarea online in 30 de secunde",
            "Facturare online cu e-Factura inclusa",
        ],
        descriptions=[
            "Emite si trimite facturi online, cu incasare automata prin card.",
            "Incepe gratuit astazi.",
        ],
    ),
    AdGroupInput(
        ad_group_id="ag_efactura",
        name="e-Factura SPV",
        exact_match_keyword="e-factura spv",
        headlines=[
            "Trimite e-Factura in SPV automat",
            "e-Factura fara pasi manuali",
        ],
        descriptions=[
            "Conectam contul si trimitem facturile in SPV pentru tine.",
        ],
    ),
    AdGroupInput(
        ad_group_id="ag_gestiune_stocuri",
        name="Gestiune stocuri",
        exact_match_keyword="gestiune stocuri",
        headlines=[
            "Software complet pentru afacerea ta",
            "Tine totul sub control",
        ],
        descriptions=[
            "Solutie all-in-one pentru firme mici.",
        ],
    ),
)


def sample_ad_groups() -> list[AdGroupInput]:
    """Returneaza copiile de anunt de exemplu (deterministic)."""
    return [group.model_copy(deep=True) for group in _SAMPLE_AD_GROUPS]
