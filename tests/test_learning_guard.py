"""Garda fazei de invatare: ce trece si ce se amana cat timp un ad set invata."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ppc_agent.decision.learning_guard import LearningState, learning_hold

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _state(
    status: str, *, days: float = 2, spend: str = "300", conversions: float = 10
) -> LearningState:
    return LearningState(
        status=status,
        since=NOW - timedelta(days=days),
        spend=Decimal(spend),
        conversions=conversions,
    )


def test_fara_stare_sau_dupa_invatare_nimic_nu_se_amana() -> None:
    assert learning_hold(None, change="major", now=NOW) is None
    assert learning_hold(_state("SUCCESS"), change="major", now=NOW) is None


@pytest.mark.parametrize(("change", "held"), [("0.10", False), ("0.20", False), ("0.50", True)])
def test_in_invatare_trece_doar_bugetul_schimbat_putin(change: str, held: bool) -> None:
    reason = learning_hold(
        _state("LEARNING"), change="budget", budget_change=Decimal(change), now=NOW
    )
    assert (reason is not None) is held


def test_in_invatare_o_modificare_majora_se_amana() -> None:
    reason = learning_hold(_state("LEARNING"), change="major", now=NOW)
    assert reason is not None and "reporni invatarea" in reason


def test_bugetul_necunoscut_e_tratat_ca_modificare_majora() -> None:
    assert learning_hold(_state("LEARNING"), change="budget", budget_change=None, now=NOW)


def test_dupa_7_zile_in_invatare_interdictia_cade() -> None:
    assert learning_hold(_state("LEARNING", days=7), change="major", now=NOW) is None


@pytest.mark.parametrize("status", ["FAIL", "LEARNING_LIMITED"])
def test_learning_limited_cu_cpa_la_tinta_e_practic_incheiata(status: str) -> None:
    # 300 lei / 10 conversii = 30 lei, tinta 35.
    state = _state(status)
    assert learning_hold(state, change="major", target_cpa=Decimal("35"), now=NOW) is None


def test_learning_limited_cu_cpa_peste_tinta_se_comporta_ca_invatarea() -> None:
    state = _state("FAIL")
    reason = learning_hold(state, change="major", target_cpa=Decimal("20"), now=NOW)
    assert reason is not None and "Learning Limited" in reason


def test_learning_limited_fara_conversii_nu_se_considera_la_tinta() -> None:
    state = _state("FAIL", conversions=0)
    assert learning_hold(state, change="major", target_cpa=Decimal("35"), now=NOW)
