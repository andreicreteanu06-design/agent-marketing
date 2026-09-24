"""Teste pentru consolidarea de lichiditate algoritmica Meta."""

from __future__ import annotations

from decimal import Decimal

from ppc_agent.alignment.meta_liquidity import consolidation_plan, learning_exit_days
from ppc_agent.alignment.models import AdSet


def _ad_set(
    ad_set_id: str,
    audience: str,
    weekly_conversions: float,
    *,
    learning: bool = True,
) -> AdSet:
    return AdSet(
        ad_set_id=ad_set_id,
        name=ad_set_id,
        audience_def=audience,
        weekly_conversions=weekly_conversions,
        weekly_spend=Decimal("100"),
        learning_phase=learning,
    )


def test_five_weak_same_audience_merge_into_one_above_threshold() -> None:
    ad_sets = [
        _ad_set(f"as{i}", "femei 25 34 fitness sport nutritie", 12.0) for i in range(5)
    ]
    plan = consolidation_plan(ad_sets, target_weekly_conversions=50)

    assert len(plan.merges) == 1
    merge = plan.merges[0]
    assert sorted(merge.source_ids) == [f"as{i}" for i in range(5)]
    assert merge.projected_weekly_conversions == 60.0
    assert merge.clears_threshold
    assert plan.recommend_cbo


def test_healthy_ad_set_is_left_untouched() -> None:
    ad_sets = [
        _ad_set("healthy", "audienta larga", 80.0, learning=False),
        _ad_set("weak_a", "nisa foarte specifica una", 10.0),
        _ad_set("weak_b", "nisa foarte specifica una", 12.0),
    ]
    plan = consolidation_plan(ad_sets, target_weekly_conversions=50)

    assert plan.untouched_ids == ["healthy"]
    merged_sources = {sid for merge in plan.merges for sid in merge.source_ids}
    assert merged_sources == {"weak_a", "weak_b"}


def test_merge_that_cannot_clear_threshold_is_flagged() -> None:
    ad_sets = [
        _ad_set("a", "audienta unica alfa", 8.0),
        _ad_set("b", "audienta unica beta", 9.0),
    ]
    plan = consolidation_plan(ad_sets, target_weekly_conversions=50)

    assert len(plan.merges) == 1
    merge = plan.merges[0]
    assert not merge.clears_threshold
    assert merge.learning_exit_days is None
    assert any("prag" in warning for warning in merge.warnings)


def test_disjoint_audiences_are_merged_when_needed_to_reach_threshold() -> None:
    ad_sets = [
        _ad_set("grp_a1", "sportivi alergare munte", 20.0),
        _ad_set("grp_a2", "sportivi alergare sosea", 18.0),
        _ad_set("grp_b1", "parinti copii scoala primara", 22.0),
    ]
    plan = consolidation_plan(ad_sets, target_weekly_conversions=50)

    # Grupul "sportivi" (38) nu atinge singur pragul -> se fuzioneaza si cu "parinti".
    assert len(plan.merges) == 1
    assert sorted(plan.merges[0].source_ids) == ["grp_a1", "grp_a2", "grp_b1"]
    assert plan.merges[0].projected_weekly_conversions == 60.0
    assert plan.merges[0].clears_threshold


def test_learning_exit_days_formula() -> None:
    # 70 conversii/sapt -> 10/zi -> 50/10 = 5 zile.
    assert learning_exit_days(70.0, 50.0) == 5.0
    # 50 conversii/sapt -> ~7.14/zi -> 7 zile (plafon nu conteaza).
    assert learning_exit_days(50.0, 50.0) == 7.0
    # Sub prag -> None.
    assert learning_exit_days(30.0, 50.0) is None


def test_recommend_cbo_only_with_real_merges() -> None:
    plan = consolidation_plan(
        [_ad_set("solo", "audienta", 20.0)], target_weekly_conversions=50
    )
    # Un singur set slab: "merge" cu o singura sursa, fara CBO.
    assert not plan.recommend_cbo
    assert plan.merges[0].source_ids == ["solo"]


def test_plan_is_deterministic() -> None:
    ad_sets = [
        _ad_set("x", "audienta comuna test", 15.0),
        _ad_set("y", "audienta comuna test", 16.0),
        _ad_set("z", "audienta comuna test", 20.0),
    ]
    first = consolidation_plan(ad_sets, 50)
    second = consolidation_plan(ad_sets, 50)
    assert first.model_dump() == second.model_dump()
