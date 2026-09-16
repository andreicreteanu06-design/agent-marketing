"""Forecasting: proiecteaza metricile viitoare ale unui brat, dintr-o serie zilnica.

Etapa NOUA care se conecteaza inaintea lui Kelly/Thompson, nu in locul lor:
:func:`apply_forecast` produce o lista de :class:`~ppc_agent.decision.models.ArmStats`
PROIECTATE - acelasi tip pe care ``kelly_sizing.size_daily_budget`` si
``budget.ThompsonBudgetAllocator`` il primesc deja azi. Niciuna din cele doua
nu se modifica: nu conteaza pentru ele daca ArmStats vine din istoricul brut
sau dintr-o proiectie. Vezi ``pipeline.py`` (parametrii optionali ``forecaster``/
``histories`` ai lui ``run_plan``) pentru cum se cupleaza efectiv - implicit
(``forecaster=None``) comportamentul ramane exact cel de azi.

Doua implementari, acelasi principiu mock-first ca peste tot in proiect:

- :class:`MockForecaster` — regresie liniara determinista pe fiecare metrica,
  fara retea si fara ML. Implicit.
- :class:`LiveTimesFmForecaster` — TimesFM 2.5 (Google Research): model
  fundament de serii de timp, pre-antrenat, zero-shot (nu are nevoie sa fie
  (re)antrenat pe contul clientului ca sa produca o proiectie rezonabila).
  Opt-in - vezi ``requirements-timesfm.txt``. Foloseste explicit checkpoint-ul
  ``2.5`` (greutati Apache-2.0, sigur comercial) - NU ``3.0`` (licenta
  non-comerciala a greutatilor) - vezi ``_TIMESFM_CHECKPOINT``, deliberat un
  constant de cod, nu o setare de mediu, ca nimeni sa nu-l poata schimba din
  greseala la 3.0 intr-un context comercial.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np

from ppc_agent.decision.models import ArmForecast, ArmStats, DailyArmMetric
from ppc_agent.errors import SetupRequiredError

_CENT = Decimal("0.01")

_TIMESFM_CHECKPOINT = "google/timesfm-2.5-200m-pytorch"
_TIMESFM_MAX_CONTEXT = 1024
_TIMESFM_MAX_HORIZON = 256
# ~80% interval (percentilele 10-90) - acelasi nivel pe care TimesFM il da nativ
# ca decile, ca MockForecaster si LiveTimesFmForecaster sa fie comparabile.
_CONFIDENCE_Z = 1.2816


class Forecaster(ABC):
    """Proiecteaza metricile viitoare ale unui brat, dintr-o serie zilnica istorica."""

    @abstractmethod
    def forecast_arm(
        self,
        arm_id: str,
        name: str,
        platform: str,
        history: list[DailyArmMetric],
        *,
        horizon_days: int,
    ) -> ArmForecast:
        """Proiecteaza urmatoarele ``horizon_days`` zile pentru un brat."""


def apply_forecast(
    arms: list[ArmStats],
    histories: dict[str, list[DailyArmMetric]],
    forecaster: Forecaster,
    *,
    horizon_days: int,
) -> list[ArmStats]:
    """Inlocuieste, per brat, ``ArmStats`` istoric cu proiectia ``forecaster``.

    Bratele fara istoric in ``histories`` raman NESCHIMBATE (fallback sigur -
    Kelly/Thompson vad pentru ele exact ce vad azi, fara proiectie).
    """
    forecasted: list[ArmStats] = []
    for arm in arms:
        history = histories.get(arm.arm_id)
        if not history:
            forecasted.append(arm)
            continue
        result = forecaster.forecast_arm(
            arm.arm_id, arm.name, arm.platform, history, horizon_days=horizon_days
        )
        forecasted.append(result.projected)
    return forecasted


def _linear_trend(values: list[float]) -> tuple[float, float, float]:
    """Regresie liniara (cele mai mici patrate): panta, intercept, abaterea std a reziduurilor.

    ``values[i]`` corespunde zilei ``i`` (0-indexat). Cu mai putin de 2 puncte
    distincte pe axa X, nu exista trend de detectat - panta 0, valoarea medie.
    """
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0), 0.0

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0.0:
        return 0.0, mean_y, 0.0

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True)) / var_x
    intercept = mean_y - slope * mean_x
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, values, strict=True)]
    residual_std = math.sqrt(sum(r * r for r in residuals) / n)
    return slope, intercept, residual_std


def _project_sum(values: list[float], *, horizon_days: int) -> tuple[float, float]:
    """Suma proiectata pe ``horizon_days`` zile viitoare, plus abaterea std a sumei.

    Math: tratand reziduurile zilnice ca aproximativ iid, varianta unei sume de
    ``horizon_days`` termeni iid e ``horizon_days * varianta_per_zi``, deci
    abaterea standard a sumei e ``residual_std * sqrt(horizon_days)``. Fiecare
    zi proiectata e taiata la minim 0 (clicks/conversii/cost nu pot fi negative).
    """
    n = len(values)
    slope, intercept, residual_std = _linear_trend(values)
    total = sum(max(0.0, slope * (n + i) + intercept) for i in range(horizon_days))
    total_std = residual_std * math.sqrt(horizon_days)
    return total, total_std


def _quantise(value: float) -> Decimal:
    return Decimal(str(round(max(0.0, value), 2))).quantize(_CENT, rounding=ROUND_HALF_UP)


class MockForecaster(Forecaster):
    """Regresie liniara determinista pe fiecare metrica - fara retea, fara ML.

    Implicit (mock-first): suficient de rezonabil ca sa foloseasca fluxul
    complet (forecast -> Kelly -> Thompson) fara sa astepte un checkpoint ML
    descarcat. Nu pretinde acuratetea unui model fundament ca TimesFM.
    """

    def forecast_arm(
        self,
        arm_id: str,
        name: str,
        platform: str,
        history: list[DailyArmMetric],
        *,
        horizon_days: int,
    ) -> ArmForecast:
        if not history:
            empty = ArmStats(
                arm_id=arm_id, name=name, platform=platform, clicks=0, conversions=0
            )
            return ArmForecast(
                projected=empty, conversions_low=0.0, conversions_high=0.0, method="trend"
            )

        ordered = sorted(history, key=lambda point: point.date)
        clicks_total, _ = _project_sum(
            [float(p.clicks) for p in ordered], horizon_days=horizon_days
        )
        conversions_total, conversions_std = _project_sum(
            [float(p.conversions) for p in ordered], horizon_days=horizon_days
        )
        cost_total, _ = _project_sum([float(p.cost) for p in ordered], horizon_days=horizon_days)
        revenue_total, _ = _project_sum(
            [float(p.revenue) for p in ordered], horizon_days=horizon_days
        )

        projected = ArmStats(
            arm_id=arm_id,
            name=name,
            platform=platform,
            clicks=round(clicks_total),
            conversions=round(conversions_total),
            cost=_quantise(cost_total),
            revenue=_quantise(revenue_total),
        )
        return ArmForecast(
            projected=projected,
            conversions_low=max(0.0, conversions_total - _CONFIDENCE_Z * conversions_std),
            conversions_high=conversions_total + _CONFIDENCE_Z * conversions_std,
            method="trend",
        )


def _load_timesfm_model() -> Any:
    """Incarca + compileaza modelul TimesFM real - retea, la prima folosire.

    Import deliberat DINAUNTRU functiei (nu la nivel de modul): ``timesfm``/
    ``torch`` sunt dependinte OPTIONALE (``requirements-timesfm.txt``), nu fac
    parte din ``requirements.txt`` de baza - restul pachetului (CLI, teste,
    mypy) trebuie sa functioneze si fara ele instalate.
    """
    import timesfm

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(_TIMESFM_CHECKPOINT)
    model.compile(
        timesfm.ForecastConfig(
            max_context=_TIMESFM_MAX_CONTEXT,
            max_horizon=_TIMESFM_MAX_HORIZON,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=True,
            fix_quantile_crossing=True,
        )
    )
    return model


class LiveTimesFmForecaster(Forecaster):
    """TimesFM 2.5 (Google Research) - model fundament de serii de timp, zero-shot.

    ``model_loader`` e un punct de injectie pentru teste (acelasi principiu ca
    parametrul ``transport`` din :class:`~seo_geo_agent.llm.LiveLLMClient`) -
    implicit, incarca modelul real (:func:`_load_timesfm_model` - retea + torch).
    Modelul se incarca o singura data, lenes (la primul ``forecast_arm``), si
    se retine pe instanta.
    """

    def __init__(self, *, model_loader: Callable[[], Any] | None = None) -> None:
        self._model_loader = model_loader or _load_timesfm_model
        self._model: Any | None = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                self._model = self._model_loader()
            except Exception as exc:
                raise SetupRequiredError(
                    f"TimesFM nu a putut fi incarcat ({exc}). Ruleaza "
                    "'pip install -r requirements-timesfm.txt' si verifica conexiunea "
                    "la internet (prima folosire descarca checkpoint-ul de pe "
                    f"Hugging Face: {_TIMESFM_CHECKPOINT})."
                ) from exc
        return self._model

    def forecast_arm(
        self,
        arm_id: str,
        name: str,
        platform: str,
        history: list[DailyArmMetric],
        *,
        horizon_days: int,
    ) -> ArmForecast:
        if not history:
            empty = ArmStats(
                arm_id=arm_id, name=name, platform=platform, clicks=0, conversions=0
            )
            return ArmForecast(
                projected=empty, conversions_low=0.0, conversions_high=0.0, method="timesfm"
            )

        model = self._get_model()
        ordered = sorted(history, key=lambda point: point.date)
        metric_names = ["clicks", "conversions", "cost", "revenue"]
        series = {
            "clicks": np.array([float(p.clicks) for p in ordered]),
            "conversions": np.array([float(p.conversions) for p in ordered]),
            "cost": np.array([float(p.cost) for p in ordered]),
            "revenue": np.array([float(p.revenue) for p in ordered]),
        }

        point_forecast, quantile_forecast = model.forecast(
            horizon=horizon_days, inputs=[series[name_] for name_ in metric_names]
        )
        totals = {
            metric_name: float(np.asarray(point_forecast[i]).sum())
            for i, metric_name in enumerate(metric_names)
        }

        # quantile_forecast: forma (serii, orizont, 10) - coloana 0 e media,
        # coloanele 1..9 sunt decilele 10..90 (vezi docstring-ul modulului).
        # Insumam decilele 10/90 pe tot orizontul pentru un interval de
        # incredere pe TOTALUL proiectat, nu doar pe ultima zi.
        conv_idx = metric_names.index("conversions")
        conversions_low = float(np.asarray(quantile_forecast[conv_idx, :, 1]).sum())
        conversions_high = float(np.asarray(quantile_forecast[conv_idx, :, 9]).sum())

        projected = ArmStats(
            arm_id=arm_id,
            name=name,
            platform=platform,
            clicks=max(0, round(totals["clicks"])),
            conversions=max(0, round(totals["conversions"])),
            cost=_quantise(totals["cost"]),
            revenue=_quantise(totals["revenue"]),
        )
        return ArmForecast(
            projected=projected,
            conversions_low=max(0.0, conversions_low),
            conversions_high=max(0.0, conversions_high),
            method="timesfm",
        )
