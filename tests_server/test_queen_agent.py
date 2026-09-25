"""Regina (agentul CMO): atribuirea cererii, simularea reactiilor, directiva.

Totul aici e pur - fara DB, fara HTTP. Scenariul de baza e un service de cutii
automate: clientii care CUMPARA vor programare simpla, iar reclama Meta care
ruleaza e plina de jargon tehnic, desi CPA-ul ei e sub tinta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ppc_agent_server.services.queen_agent import (
    DOMINANT_SHARE,
    BrandSignals,
    BrandStrategist,
    LiveAd,
    SearchSignal,
    build_directive,
    classify_query,
    simulate_reactions,
    technical_density,
)

NOW = datetime(2026, 9, 25, tzinfo=UTC)

TECHNICAL_AD = LiveAd(
    ref="meta_ad/111",
    platform="meta",
    headline="Schimb ulei ATF cutie automata",
    body=(
        "Procedura dinamica cu aparat dedicat, ulei ATF Dexron VI si filtru OEM. "
        "Specificatii la cerere."
    ),
    spend=Decimal("620"),
    conversions=9,
    target_cpa=Decimal("80"),
)
CONVENIENCE_AD = LiveAd(
    ref="ad_queue_item/7",
    platform="google",
    headline="Programare online în 2 minute | Gata în aceeași zi",
    body="Ne ocupăm noi de tot, fără cozi și fără bătăi de cap. Garanție 12 luni.",
)


def _searches() -> list[SearchSignal]:
    return [
        SearchSignal("programare service cutie automata", "organic", 900, 40),
        SearchSignal("service cutie automata deschis sambata", "organic", 400, 22),
        SearchSignal("schimb ulei cutie automata langa mine", "organic", 650, 30),
        SearchSignal("schimb ulei cutie automata pret", "organic", 700, 25),
        SearchSignal("garantie reparatie cutie automata", "organic", 300, 12),
        SearchSignal("cand se schimba uleiul la cutia automata", "organic", 800, 6),
        SearchSignal("autofix pareri", "organic", 120, 30),
        SearchSignal("programare online schimb ulei cutie automata", "paid", 500, 60, 14.0),
        SearchSignal("service cutie automata pret", "paid", 420, 45, 3.0),
        SearchSignal("service cutie automata garantie", "paid", 150, 18, 2.0),
        SearchSignal("cum schimbi singur uleiul la cutia automata", "paid", 380, 35, 0.0),
    ]


def _signals(**overrides: object) -> BrandSignals:
    values: dict[str, object] = {
        "brand": "autofix",
        "searches": _searches(),
        "ads": [TECHNICAL_AD, CONVENIENCE_AD],
    }
    values.update(overrides)
    return BrandSignals(**values)  # type: ignore[arg-type]


# --- atribuirea cautarilor pe profiluri ---------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("schimb ulei cutie automata pret", ("price",)),
        ("cât costă schimbul de ulei", ("price",)),  # "cat" nu e intrebare de informare
        ("service auto non stop", ("urgency",)),
        ("service cu garanție și recenzii", ("trust",)),
        ("programare online service", ("convenience",)),
        ("cand se schimba uleiul la cutia automata", ("research",)),
        ("de ce scartaie cutia automata", ("research",)),
        ("semne ulei cutie automata uzat", ("research",)),
        ("pret service cutie automata cu garantie", ("price", "trust")),
        ("service cutie automata", ()),
    ],
)
def test_classify_query(query: str, expected: tuple[str, ...]) -> None:
    assert classify_query(query) == expected


def test_classify_query_ignores_diacritics() -> None:
    assert classify_query("preț revizie") == classify_query("pret revizie") == ("price",)


def test_brand_queries_are_not_attributed() -> None:
    """Cine cauta brandul te cunoaste deja - nu spune nimic despre un client nou."""
    assert classify_query("autofix pareri", brand="autofix") == ()
    assert classify_query("autofix pareri") == ("trust",)


# --- textul tehnic si reactiile profilurilor ----------------------------------


def test_technical_density_flags_jargon_but_not_caps_emphasis() -> None:
    assert technical_density(TECHNICAL_AD.text) >= 0.15
    assert technical_density(CONVENIENCE_AD.text) < 0.15
    assert technical_density("OFERTA NOU ACUM la schimbul de ulei") == 0.0


def test_technical_ad_repels_the_busy_customer_and_attracts_the_researcher() -> None:
    reactions, technical = simulate_reactions(TECHNICAL_AD)
    by_key = {reaction.key: reaction for reaction in reactions}

    assert technical is True
    assert by_key["convenience"].stance == "opposing"
    assert by_key["convenience"].repellers_found == ["jargon tehnic"]
    assert by_key["urgency"].stance == "opposing"
    assert by_key["research"].stance == "supportive"
    assert by_key["price"].stance == "observer"


def test_reactions_cover_all_four_stances() -> None:
    reactions, _ = simulate_reactions(
        LiveAd(ref="x", platform="meta", headline="Cel mai ieftin service", body="Garanție inclusă")
    )
    by_key = {reaction.key: reaction for reaction in reactions}
    assert by_key["trust"].stance == "neutral"  # garantie, dar si "ieftin"
    assert by_key["research"].stance == "observer"

    reactions, _ = simulate_reactions(
        LiveAd(ref="y", platform="meta", headline="Service premium", body="Doar cu programare")
    )
    by_key = {reaction.key: reaction for reaction in reactions}
    assert by_key["price"].stance == "opposing"
    assert by_key["urgency"].stance == "opposing"


# --- directiva ----------------------------------------------------------------


def test_directive_picks_the_customer_who_buys_as_the_ideal_avatar() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)

    assert directive.status == "ok"
    assert directive.avatar is not None
    assert directive.avatar.key == "convenience"
    assert directive.avatar.dominant
    top = directive.segments[0]
    # Cercetatorul face o parte mare din cerere, dar nu cumpara - nu e clientul ideal.
    research = next(s for s in directive.segments if s.key == "research")
    assert research.demand_share > 0.2
    assert research.buyer_share == 0.0
    assert top.buyer_share is not None and top.buyer_share > 0.7
    assert directive.ideal_avatar_profile.startswith("Clientul ideal: «Ocupatul pragmatic»")
    assert "programare online schimb ulei cutie automata" in directive.avatar.sample_queries


def test_technical_ad_is_forced_to_rewrite_even_with_a_stable_cpa() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    by_ref = {ad.ref: ad for ad in directive.ad_alignment}

    technical = by_ref["meta_ad/111"]
    assert technical.cpa == Decimal("68.89")
    assert technical.cpa < Decimal("80")  # matematic, reclama e "buna"
    assert technical.deviates
    assert technical.avatar_stance == "opposing"
    assert technical.speaks_to == "research"
    assert "pare stabilă" in technical.reason

    aligned = by_ref["ad_queue_item/7"]
    assert not aligned.deviates
    assert aligned.avatar_stance == "supportive"
    assert aligned.alignment_score > technical.alignment_score
    assert [ad.ref for ad in directive.misaligned_ads] == ["meta_ad/111"]


def test_copywriting_angle_speaks_the_copywriter_vocabulary() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    angle = directive.copywriting_angle

    assert angle is not None
    assert angle.summary.startswith("Schimbă textele din tehnice în texte despre timp salvat")
    assert angle.emotion_trigger == "economie de timp"  # stilul "aida" din swipe.py
    assert "Programare online în 2 minute" in angle.hooks
    assert any("jargon tehnic" in item for item in angle.avoid)


def test_targeting_excludes_the_profile_that_clicks_but_never_buys() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    kinds = {adjustment.kind: adjustment for adjustment in directive.targeting_adjustments}

    assert "Programează-te" in kinds["delivery"].suggestion
    assert "Do it yourself" in kinds["exclusion"].suggestion
    assert "35 de click-uri plătite" in kinds["exclusion"].reason
    assert "cutie" in kinds["interest"].suggestion
    # 19 conversii nu ajung pentru audienta-sursa a unui lookalike (minim 100).
    assert "audience" not in kinds


def test_lookalike_needs_a_hundred_conversions() -> None:
    searches = [*_searches(), SearchSignal("programare online service", "paid", 5000, 900, 120.0)]
    directive = build_directive(42, _signals(searches=searches), generated_at=NOW)
    assert any(adj.kind == "audience" for adj in directive.targeting_adjustments)


def test_demographics_are_never_invented() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    text = directive.ideal_avatar_profile.lower()
    for invented in ("bărbat", "femeie", " ani"):
        assert invented not in text
    assert any("Vârsta și genul" in note for note in directive.notes)


def test_insufficient_data_produces_no_avatar_and_no_rewrites() -> None:
    signals = _signals(searches=[SearchSignal("service cutie automata pret", "paid", 40, 3, 0.0)])
    directive = build_directive(42, signals, generated_at=NOW)

    assert directive.status == "insufficient_data"
    assert directive.avatar is None
    assert directive.copywriting_angle is None
    assert directive.targeting_adjustments == []
    assert directive.misaligned_ads == []
    assert directive.ideal_avatar_profile.startswith(
        "Date insuficiente pentru un client ideal: o căutare atribuită, cu 40 de afișări "
        "și 0 conversii"
    )


def test_split_demand_does_not_force_rewrites() -> None:
    """Fara un profil dominant, a rescrie totul pentru unul singur i-ar pierde pe ceilalti."""
    searches = [
        SearchSignal("service cutie automata pret", "organic", 500, 10),
        SearchSignal("service cutie automata garantie", "organic", 500, 10),
        SearchSignal("programare service cutie automata", "organic", 500, 10),
        SearchSignal("service cutie automata non stop", "organic", 500, 10),
        SearchSignal("semne cutie automata defecta", "organic", 10, 1),
    ]
    directive = build_directive(42, _signals(searches=searches), generated_at=NOW)

    assert directive.status == "ok"
    assert directive.avatar is not None
    assert directive.avatar.share < DOMINANT_SHARE
    assert not directive.avatar.dominant
    assert directive.misaligned_ads == []
    assert "testat A/B" in directive.ideal_avatar_profile


def test_directive_is_deterministic() -> None:
    first = build_directive(42, _signals(), generated_at=NOW)
    second = build_directive(42, _signals(), generated_at=NOW)
    assert first.model_dump() == second.model_dump()


def test_brand_strategist_reads_through_the_injected_source() -> None:
    calls: list[int] = []

    class _Source:
        def load(self, client_account_id: int) -> BrandSignals:
            calls.append(client_account_id)
            return _signals()

    directive = BrandStrategist(_Source(), clock=lambda: NOW).evaluate_brand_alignment(7)

    assert calls == [7]
    assert directive.client_account_id == 7
    assert directive.generated_at == NOW
