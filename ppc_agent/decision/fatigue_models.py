"""Structuri de date tipizate pentru monitorul de oboseala a anunturilor.

Vezi :mod:`ppc_agent.decision.fatigue_monitor` pentru portile de decizie
(Kill Switch / Pruning Switch) care consuma :class:`AdPerformanceState`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FatiguePlatform = Literal["meta", "tiktok", "google"]
AdStatus = Literal["new", "profitable", "fatigued"]
FatigueVerdict = Literal[
    "CONTINUE", "PAUSE_HARD", "PAUSE_PROVISIONAL", "HOLD_FOR_LAG", "PAUSE_REPLACE"
]


class AdPerformanceState(BaseModel):
    """Instantaneul de performanta al unui anunt, la un moment dat.

    Cele 6 campuri de dupa ``bad_days_last_5`` (``ctr_3d`` si urmatoarele) nu
    erau in lista initiala de campuri ceruta explicit, dar sunt indispensabile
    formulelor Gate C (Pruning Switch, vezi fatigue_monitor.py): perechea
    ``ctr``/``account_median_ctr`` e o comparatie INCRUCISATA (acest anunt
    fata de restul contului) - folosita de Gate B pentru anunturi noi, care
    inca nu au istoric propriu. Oboseala creativa (Gate C) cere insa o
    comparatie de TENDINTA (recent fata de propriul istoric al anuntului),
    imposibil de derivat din ``ctr``/``account_median_ctr``, si Meta/TikTok
    folosesc ferestre de baza diferite (14 zile, respectiv 7 zile) - de-asta
    doua campuri separate de baza CTR/CPA, nu unul comun. Adaugate cu valoare
    implicita 0 (ca ``frequency_7d``/``six_second_view_rate``, deja explicite
    in cerere) ca sa nu afecteze constructia in Gate B/teste care nu ating
    Gate C.
    """

    ad_id: str
    platform: FatiguePlatform
    status: AdStatus
    launch_time: datetime
    spend: float = Field(ge=0)
    target_cpa: float = Field(gt=0)
    conversions: int = Field(ge=0)
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    ctr: float = Field(ge=0)
    account_median_ctr: float = Field(ge=0)
    frequency_7d: float = Field(default=0.0, ge=0)
    six_second_view_rate: float = Field(default=0.0, ge=0)
    cpa_3d: float = Field(ge=0)
    cpa_baseline_14d: float = Field(ge=0)
    bad_days_last_5: int = Field(ge=0)

    # Adaugate fata de lista explicita din cerere - vezi docstring-ul de mai sus.
    ctr_3d: float = Field(default=0.0, ge=0)
    ctr_baseline_14d: float = Field(default=0.0, ge=0)
    ctr_baseline_7d: float = Field(default=0.0, ge=0)
    cpa_baseline_7d: float = Field(default=0.0, ge=0)
    six_second_view_rate_baseline: float = Field(default=0.0, ge=0)
    bad_days_last_3: int = Field(default=0, ge=0)
