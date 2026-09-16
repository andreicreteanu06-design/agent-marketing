"""Teste deterministe pentru forecasting (etapa noua, inaintea Kelly/Thompson).

``LiveTimesFmForecaster`` e testat cu un ``model_loader`` fals (acelasi
principiu ca ``transport`` la ``LiveLLMClient``) - fara retea, fara torch/timesfm
reale in suita, la fel cum testele server nu ating vreodata Redis/Postgres reale.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from ppc_agent.decision.forecasting import LiveTimesFmForecaster, MockForecaster, apply_forecast
from ppc_agent.decision.models import ArmStats, DailyArmMetric
from ppc_agent.errors import SetupRequiredError

_START = date(2026, 1, 1)


def _history(values: list[float]) -> list[DailyArmMetric]:
    """O zi per valoare din ``values`` - conversii = valoare, clicks/cost/revenue x10/x2."""
    return [
        DailyArmMetric(
            date=_START + timedelta(days=i),
            clicks=round(value * 10),
            conversions=round(value),
            cost=Decimal(str(value)),
            revenue=Decimal(str(value * 2)),
        )
        for i, value in enumerate(values)
    ]


class TestMockForecaster:
    def test_flat_series_projects_constant_total(self) -> None:
        # 10 conversii/zi timp de 10 zile -> fara trend, proiectia e 10/zi.
        forecaster = MockForecaster()
        result = forecaster.forecast_arm(
            "arm-1", "Arm 1", "google_ads", _history([10.0] * 10), horizon_days=7
        )
        assert result.projected.conversions == 70
        assert result.method == "trend"
        # Fara variatie in istoric -> abatere standard 0 -> interval degenerat.
        assert result.conversions_low == pytest.approx(70.0)
        assert result.conversions_high == pytest.approx(70.0)

    def test_detects_upward_trend(self) -> None:
        # conversii = 1..10 (trend perfect liniar: panta 1, intercept 1).
        forecaster = MockForecaster()
        result = forecaster.forecast_arm(
            "arm-1", "Arm 1", "google_ads", _history(list(range(1, 11))), horizon_days=5
        )
        # Zilele 10..14 (0-indexat): 1*(10+i)+1 pentru i=0..4 -> 11,12,13,14,15 -> suma 65.
        assert result.projected.conversions == 65
        # Fit perfect (reziduuri 0) -> interval degenerat in jurul proiectiei.
        assert result.conversions_low == pytest.approx(65.0, abs=0.01)
        assert result.conversions_high == pytest.approx(65.0, abs=0.01)

    def test_empty_history_returns_zeroed_arm(self) -> None:
        forecaster = MockForecaster()
        result = forecaster.forecast_arm("arm-1", "Arm 1", "google_ads", [], horizon_days=7)
        assert result.projected == ArmStats(
            arm_id="arm-1", name="Arm 1", platform="google_ads", clicks=0, conversions=0
        )
        assert result.conversions_low == 0.0
        assert result.conversions_high == 0.0

    def test_projection_never_negative_on_downward_trend(self) -> None:
        # Trend puternic descrescator -> fara proiectia taiata la 0, ar deveni negativa.
        forecaster = MockForecaster()
        result = forecaster.forecast_arm(
            "arm-1", "Arm 1", "google_ads", _history([20.0, 10.0, 0.0]), horizon_days=10
        )
        assert result.projected.conversions >= 0
        assert result.projected.clicks >= 0


class TestApplyForecast:
    def test_replaces_only_arms_with_history(self) -> None:
        arm_with_history = ArmStats(
            arm_id="a",
            name="A",
            clicks=100,
            conversions=10,
            cost=Decimal("50"),
            revenue=Decimal("100"),
        )
        arm_without_history = ArmStats(
            arm_id="b",
            name="B",
            clicks=200,
            conversions=20,
            cost=Decimal("80"),
            revenue=Decimal("200"),
        )
        histories = {"a": _history([5.0] * 5)}

        result = apply_forecast(
            [arm_with_history, arm_without_history],
            histories,
            MockForecaster(),
            horizon_days=7,
        )

        assert result[0].arm_id == "a"
        assert result[0].conversions == 35  # 5/zi * 7 zile proiectate
        assert result[1] == arm_without_history  # neschimbat - fara istoric

    def test_empty_histories_dict_leaves_all_arms_unchanged(self) -> None:
        arm = ArmStats(arm_id="a", name="A", clicks=100, conversions=10)
        result = apply_forecast([arm], {}, MockForecaster(), horizon_days=7)
        assert result == [arm]


class _FakeTimesFmModel:
    """Stand-in determinist pentru modelul TimesFM real - fara torch, fara retea."""

    def __init__(self) -> None:
        self.calls = 0

    def forecast(
        self, *, horizon: int, inputs: list[np.ndarray]
    ) -> tuple[np.ndarray, np.ndarray]:
        self.calls += 1
        n_series = len(inputs)
        point_forecast = np.full((n_series, horizon), 2.0)
        quantile_forecast = np.zeros((n_series, horizon, 10))
        quantile_forecast[:, :, 1] = 1.0  # decila 10
        quantile_forecast[:, :, 9] = 3.0  # decila 90
        return point_forecast, quantile_forecast


class TestLiveTimesFmForecaster:
    def test_happy_path_sums_point_forecast_and_reads_decile_columns(self) -> None:
        fake_model = _FakeTimesFmModel()
        forecaster = LiveTimesFmForecaster(model_loader=lambda: fake_model)

        result = forecaster.forecast_arm(
            "arm-1", "Arm 1", "meta_ads", _history([1.0, 2.0, 3.0]), horizon_days=4
        )

        # point_forecast e 2.0 in fiecare din cele 4 zile proiectate -> suma 8.0 per metrica.
        assert result.projected.clicks == 8
        assert result.projected.conversions == 8
        assert result.projected.cost == Decimal("8.00")
        assert result.projected.revenue == Decimal("8.00")
        # decila 10 = 1.0 x 4 zile = 4.0 ; decila 90 = 3.0 x 4 zile = 12.0.
        assert result.conversions_low == pytest.approx(4.0)
        assert result.conversions_high == pytest.approx(12.0)
        assert result.method == "timesfm"

    def test_model_loaded_lazily_and_cached_across_calls(self) -> None:
        fake_model = _FakeTimesFmModel()
        load_count = 0

        def _loader() -> _FakeTimesFmModel:
            nonlocal load_count
            load_count += 1
            return fake_model

        forecaster = LiveTimesFmForecaster(model_loader=_loader)
        assert load_count == 0  # nimic incarcat la constructie

        forecaster.forecast_arm("a", "A", "google_ads", _history([1.0, 2.0]), horizon_days=2)
        forecaster.forecast_arm("b", "B", "google_ads", _history([3.0, 4.0]), horizon_days=2)
        assert load_count == 1  # incarcat o singura data, refolosit la al doilea apel

    def test_empty_history_returns_zero_without_loading_model(self) -> None:
        def _loader() -> _FakeTimesFmModel:
            raise AssertionError("modelul nu trebuie incarcat pentru istoric gol")

        forecaster = LiveTimesFmForecaster(model_loader=_loader)
        result = forecaster.forecast_arm("a", "A", "google_ads", [], horizon_days=7)
        assert result.projected == ArmStats(
            arm_id="a", name="A", platform="google_ads", clicks=0, conversions=0
        )
        assert result.method == "timesfm"

    def test_loader_failure_raises_setup_required_error(self) -> None:
        def _failing_loader() -> _FakeTimesFmModel:
            raise RuntimeError("nu s-a putut descarca checkpoint-ul")

        forecaster = LiveTimesFmForecaster(model_loader=_failing_loader)
        with pytest.raises(SetupRequiredError, match="TimesFM"):
            forecaster.forecast_arm("a", "A", "google_ads", _history([1.0, 2.0]), horizon_days=3)
