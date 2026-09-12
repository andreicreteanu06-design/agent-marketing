"""Teste pentru monitorul de oboseala (Kill Rules, Pruning Switch, tampon CAPI).

Acopera toate portile din cerere: Gate A (asteapta), Gate B - PAUSE_HARD,
PAUSE_PROVISIONAL, HOLD_FOR_LAG (anunturi noi) si Gate C - PAUSE_REPLACE pe
Meta si pe TikTok (anunturi profitabile, oboseala creativa).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ppc_agent.decision.fatigue_models import AdPerformanceState
from ppc_agent.decision.fatigue_monitor import (
    evaluate_ad,
    explain_verdict,
    load_ad_performance_states,
)
from ppc_agent.errors import FatigueInputError

_NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)

# Baseline "sigur": niciun camp nu atinge vreun prag - orice test porneste de
# aici si suprascrie DOAR campurile relevante pentru regula testata.
_SAFE_DEFAULTS: dict[str, Any] = dict(
    ad_id="ad_1",
    platform="google",
    status="new",
    launch_time=_NOW - timedelta(hours=200),
    spend=0.0,
    target_cpa=10.0,
    conversions=0,
    impressions=0,
    clicks=0,
    ctr=0.0,
    account_median_ctr=0.05,
    cpa_3d=0.0,
    cpa_baseline_14d=0.0,
    bad_days_last_5=0,
)

_META_FATIGUED: dict[str, Any] = dict(
    platform="meta",
    status="profitable",
    impressions=1500,
    ctr_3d=0.01,
    ctr_baseline_14d=0.02,  # 0.01 <= 75% * 0.02 = 0.015
    cpa_3d=15.0,
    cpa_baseline_14d=10.0,  # 15 >= 125% * 10 = 12.5
    frequency_7d=3.5,
    bad_days_last_5=3,
)

_TIKTOK_FATIGUED: dict[str, Any] = dict(
    platform="tiktok",
    status="profitable",
    impressions=2000,
    ctr_3d=0.01,
    ctr_baseline_7d=0.02,
    cpa_3d=15.0,
    cpa_baseline_7d=10.0,
    six_second_view_rate=0.3,
    six_second_view_rate_baseline=0.5,  # 0.3 <= 80% * 0.5 = 0.4
    bad_days_last_3=2,
)


def _ad(**overrides: Any) -> AdPerformanceState:
    fields = {**_SAFE_DEFAULTS, **overrides}
    return AdPerformanceState(**fields)


# --- Gate A: tampon de atribuire (Wait) --------------------------------------


def test_gate_a_continue_when_younger_than_buffer() -> None:
    ad = _ad(launch_time=_NOW - timedelta(hours=10))
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


def test_gate_a_just_under_48h_is_continue() -> None:
    ad = _ad(launch_time=_NOW - timedelta(hours=47, minutes=59))
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


def test_gate_a_exactly_48h_passes_the_buffer_and_reaches_gate_b() -> None:
    """La exact 48h varsta NU mai e < 48 - trece de Gate A si HOLD_FOR_LAG poate declansa."""
    ad = _ad(
        launch_time=_NOW - timedelta(hours=48),
        spend=15.0,  # 1.5x target_cpa (10)
        conversions=0,
    )
    assert evaluate_ad(ad, _NOW) == "HOLD_FOR_LAG"


def test_gate_a_ignores_status_while_too_young() -> None:
    """Chiar si un anunt 'profitabil' cu semne de oboseala asteapta daca e prea tanar."""
    ad = _ad(launch_time=_NOW - timedelta(hours=1), **_META_FATIGUED)
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


# --- Gate B: Kill Switch (anunturi noi) --------------------------------------


def test_gate_b_pause_hard_no_conversions_double_spend_old_enough() -> None:
    ad = _ad(
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,  # 2x target_cpa (10)
        conversions=0,
        impressions=1500,
    )
    assert evaluate_ad(ad, _NOW) == "PAUSE_HARD"


@pytest.mark.parametrize(
    "override",
    [
        {"conversions": 1},
        {"impressions": 1499},
        {"spend": 19.99},
        {"launch_time": _NOW - timedelta(hours=71)},
    ],
)
def test_gate_b_pause_hard_requires_every_condition(override: dict[str, Any]) -> None:
    base = dict(
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,
        conversions=0,
        impressions=1500,
    )
    ad = _ad(**{**base, **override})
    assert evaluate_ad(ad, _NOW) != "PAUSE_HARD"


def test_gate_b_pause_provisional_ctr_far_below_account_median() -> None:
    ad = _ad(impressions=1500, ctr=0.01, account_median_ctr=0.05, clicks=30)
    assert evaluate_ad(ad, _NOW) == "PAUSE_PROVISIONAL"


def test_gate_b_pause_provisional_requires_min_clicks() -> None:
    ad = _ad(impressions=1500, ctr=0.01, account_median_ctr=0.05, clicks=29)
    assert evaluate_ad(ad, _NOW) != "PAUSE_PROVISIONAL"


def test_gate_b_pause_provisional_ctr_exactly_at_half_median_triggers() -> None:
    ad = _ad(impressions=1500, ctr=0.025, account_median_ctr=0.05, clicks=30)
    assert evaluate_ad(ad, _NOW) == "PAUSE_PROVISIONAL"


def test_gate_b_hold_for_lag_spend_over_threshold_no_conversions() -> None:
    ad = _ad(launch_time=_NOW - timedelta(hours=50), spend=15.0, conversions=0)
    assert evaluate_ad(ad, _NOW) == "HOLD_FOR_LAG"


def test_gate_b_hold_for_lag_not_triggered_with_a_conversion() -> None:
    ad = _ad(launch_time=_NOW - timedelta(hours=50), spend=15.0, conversions=1)
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


def test_gate_b_pause_hard_takes_priority_over_hold_for_lag() -> None:
    """Un anunt care indeplineste ambele seturi de conditii primeste verdictul mai sever."""
    ad = _ad(
        launch_time=_NOW - timedelta(hours=72),
        spend=20.0,
        conversions=0,
        impressions=1500,
    )
    verdict = evaluate_ad(ad, _NOW)
    assert verdict == "PAUSE_HARD"


def test_gate_b_continue_when_no_rule_triggers() -> None:
    assert evaluate_ad(_ad(), _NOW) == "CONTINUE"


# --- Gate C: Pruning Switch (anunturi profitabile) ---------------------------


def test_gate_c_meta_pause_replace_on_creative_fatigue() -> None:
    ad = _ad(**_META_FATIGUED)
    assert evaluate_ad(ad, _NOW) == "PAUSE_REPLACE"


@pytest.mark.parametrize(
    "override",
    [
        {"impressions": 1499},
        {"ctr_3d": 0.016},
        {"cpa_3d": 12.4},
        {"frequency_7d": 2.9},
        {"bad_days_last_5": 2},
    ],
)
def test_gate_c_meta_requires_every_condition(override: dict[str, Any]) -> None:
    ad = _ad(**{**_META_FATIGUED, **override})
    assert evaluate_ad(ad, _NOW) != "PAUSE_REPLACE"


def test_gate_c_tiktok_pause_replace_on_creative_fatigue() -> None:
    ad = _ad(**_TIKTOK_FATIGUED)
    assert evaluate_ad(ad, _NOW) == "PAUSE_REPLACE"


@pytest.mark.parametrize(
    "override",
    [
        {"impressions": 1999},
        {"ctr_3d": 0.016},
        {"cpa_3d": 12.4},
        {"six_second_view_rate": 0.41},
        {"bad_days_last_3": 1},
    ],
)
def test_gate_c_tiktok_requires_every_condition(override: dict[str, Any]) -> None:
    ad = _ad(**{**_TIKTOK_FATIGUED, **override})
    assert evaluate_ad(ad, _NOW) != "PAUSE_REPLACE"


def test_gate_c_google_has_no_pruning_rule_defined() -> None:
    """Cererea defineste Pruning Switch doar pentru Meta/TikTok - Google trece prin."""
    ad = _ad(
        platform="google",
        status="profitable",
        impressions=999_999,
        ctr_3d=0.0,
        ctr_baseline_14d=1.0,
        cpa_3d=999.0,
        cpa_baseline_14d=1.0,
        frequency_7d=99.0,
        bad_days_last_5=99,
    )
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


def test_gate_c_meta_ad_evaluated_with_tiktok_fields_does_not_trigger() -> None:
    """Campurile TikTok (ctr_baseline_7d etc.) nu se aplica unui anunt Meta."""
    ad = _ad(**{**_TIKTOK_FATIGUED, "platform": "meta"})
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


def test_already_fatigued_ad_is_not_reevaluated() -> None:
    """Un anunt deja marcat 'fatigued' a fost deja actionat - nimic nou de facut."""
    ad = _ad(status="fatigued", **{k: v for k, v in _META_FATIGUED.items() if k != "status"})
    assert evaluate_ad(ad, _NOW) == "CONTINUE"


# --- Validare la nivel de model (limite de sistem) ---------------------------


def test_rejects_non_positive_target_cpa() -> None:
    with pytest.raises(ValidationError):
        _ad(target_cpa=0.0)


def test_rejects_negative_spend() -> None:
    with pytest.raises(ValidationError):
        _ad(spend=-1.0)


# --- explain_verdict ----------------------------------------------------------


def test_explain_verdict_pause_hard_mentions_spend_and_target() -> None:
    ad = _ad(
        launch_time=_NOW - timedelta(hours=72), spend=20.0, conversions=0, impressions=1500
    )
    reason = explain_verdict(ad, "PAUSE_HARD", _NOW)
    assert "20.00" in reason
    assert "10.00" in reason


def test_explain_verdict_distinguishes_meta_and_tiktok_pause_replace() -> None:
    meta_reason = explain_verdict(_ad(**_META_FATIGUED), "PAUSE_REPLACE", _NOW)
    tiktok_reason = explain_verdict(_ad(**_TIKTOK_FATIGUED), "PAUSE_REPLACE", _NOW)
    assert "Meta" in meta_reason
    assert "TikTok" in tiktok_reason


# --- load_ad_performance_states ------------------------------------------------


def test_load_ad_performance_states_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "ads.json"
    path.write_text(json.dumps([_ad().model_dump(mode="json")]), encoding="utf-8")
    loaded = load_ad_performance_states(path)
    assert len(loaded) == 1
    assert loaded[0].ad_id == "ad_1"


def test_load_ad_performance_states_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FatigueInputError):
        load_ad_performance_states(tmp_path / "nu_exista.json")


def test_load_ad_performance_states_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "ads.json"
    path.write_text("{ nu e json", encoding="utf-8")
    with pytest.raises(FatigueInputError):
        load_ad_performance_states(path)


def test_load_ad_performance_states_empty_list_raises(tmp_path: Path) -> None:
    path = tmp_path / "ads.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(FatigueInputError):
        load_ad_performance_states(path)


def test_load_ad_performance_states_invalid_entry_raises(tmp_path: Path) -> None:
    path = tmp_path / "ads.json"
    path.write_text(json.dumps([{"ad_id": "x"}]), encoding="utf-8")
    with pytest.raises(FatigueInputError):
        load_ad_performance_states(path)
