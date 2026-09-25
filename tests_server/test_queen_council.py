"""Consiliul Reginei: decizia e determinista, LLM-urile doar o argumenteaza.

Un LLM fals (``_CouncilVoice``) joaca toate cele trei roluri (strategul, CFO-ul,
Regina ca presedinte) si raspunde dupa promptul de sistem primit. Se verifica:
verdictul financiar din cifre, ce taie CFO-ul, ce primeste fiecare membru si ca
orice text care iese din date duce la varianta determinista, nu la o eroare.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from decimal import Decimal

import pytest

from ppc_agent_server.services.council import (
    CFO_SYSTEM_PROMPT,
    CHAIR_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
    AdSpend,
    FinancialSignals,
    QueenCouncil,
    QuestionTopic,
    TermSpend,
    build_financial_snapshot,
    check_council_text,
    classify_question,
    rule_on_question,
)
from ppc_agent_server.services.queen_agent import (
    BrandStrategyDirective,
    SearchSignal,
    build_directive,
)
from ppc_agent_server.services.technician import (
    TECHNICIAN_SYSTEM_PROMPT,
    TechnicalSignals,
    TechnicalSignalsSource,
)
from tests_server.test_queen_agent import NOW, _signals

TECHNICAL_HEADLINE = "Schimb ulei ATF cutie automata"


def _ad(
    ad_id: str = "111",
    *,
    spend: str = "620",
    conversions: int = 9,
    target: str = "80",
    label: str = TECHNICAL_HEADLINE,
    platform: str = "meta",
    revenue: str = "0",
) -> AdSpend:
    return AdSpend(
        ad_id=ad_id,
        platform=platform,
        label=label,
        spend=Decimal(spend),
        conversions=conversions,
        revenue=Decimal(revenue),
        target_cpa=Decimal(target),
    )


def _term(term: str, cost: str, conversions: float, *, value: str = "0") -> TermSpend:
    return TermSpend(
        term=term, clicks=30, cost=Decimal(cost), conversions=conversions, value=Decimal(value)
    )


PROFITABLE_TERMS = (
    _term("programare online schimb ulei cutie automata", "200", 14.0),
    _term("service cutie automata pret", "100", 3.0),
    _term("cum schimbi singur uleiul la cutia automata", "100", 0.0),
)


def _finances(
    ads: Sequence[AdSpend] = (_ad(),),
    terms: Sequence[TermSpend] = PROFITABLE_TERMS,
    *,
    objective: str = "lead_generation",
    pending: int = 2,
) -> FinancialSignals:
    return FinancialSignals(
        objective=objective,
        ads=ads,
        search_terms=terms,
        daily_spend_cap=Decimal("50"),
        pending_proposals=pending,
        window_days=30,
    )


LOSING = _finances(
    ads=(_ad(spend="900", conversions=6), _ad("222", spend="150", conversions=0, label="")),
    terms=(),
)
NO_MONEY = _finances(ads=(), terms=())


class _Static:
    def __init__(self, signals: FinancialSignals) -> None:
        self._signals = signals

    def load(self, client_account_id: int) -> FinancialSignals:
        return self._signals


_ROLE_BY_PROMPT = {
    STRATEGIST_SYSTEM_PROMPT: "strategist",
    CFO_SYSTEM_PROMPT: "cfo",
    CHAIR_SYSTEM_PROMPT: "chair",
    TECHNICIAN_SYSTEM_PROMPT: "technician",
}
STRATEGIST_SAYS = (
    "Clientul tău ideal e «Ocupatul pragmatic»: vrea să rezolve totul din telefon. Reclama "
    "«Schimb ulei ATF cutie automata» îi vorbește tehnic, pe limba altui public."
)
CFO_SAYS = (
    "Contul e rentabil: CPA-ul e 39,23 RON, sub ținta de 80 RON. Merită crescut doar ce aduce "
    "deja clienți, în plafonul de 50 RON pe zi."
)
TECHNICIAN_SAYS = "Tracking: roșu. Conversiile Google Ads tac. Nu e marketing, e tag-ul."
CHAIR_SAYS = (
    "Da, dar controlat. Contul e rentabil - CPA 39,23 RON, sub ținta de 80 RON - deci "
    "cheltuiala poate crește treptat, doar pe ce aduce deja clienți, în plafonul de 50 RON pe zi. "
    "Publicul care contează e «Ocupatul pragmatic», iar reclama tehnică o rescriem ca test A/B. "
    "Orice creștere vine ca propunere pe care o aprobi tu."
)


class _CouncilVoice:
    """LLM-ul fals al consiliului: raspunde dupa rol si tine minte ce a primit."""

    model = "fake/council"

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.answers = {
            "strategist": STRATEGIST_SAYS,
            "cfo": CFO_SAYS,
            "technician": TECHNICIAN_SAYS,
            "chair": CHAIR_SAYS,
        }
        self.answers.update(answers or {})
        self.errors = errors or {}
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def complete(self, *, system: str, user: str) -> str:
        role = _ROLE_BY_PROMPT[system]
        with self._lock:
            self.calls.append((role, user))
        if role in self.errors:
            raise self.errors[role]
        return self.answers[role]

    def prompt(self, role: str) -> str:
        return next(user for called, user in self.calls if called == role)

    @property
    def roles(self) -> list[str]:
        return sorted(role for role, _ in self.calls)


def _directive(**overrides: object) -> BrandStrategyDirective:
    return build_directive(42, _signals(**overrides), generated_at=NOW)


THIN_DIRECTIVE_SIGNALS = {"searches": [SearchSignal("service cutie automata pret", "paid", 40, 3)]}


class _StaticTechnical:
    def __init__(self, signals: TechnicalSignals) -> None:
        self._signals = signals

    def load(self, client_account_id: int) -> TechnicalSignals:
        return self._signals


def _council(
    finances: FinancialSignals | None = None,
    voice: _CouncilVoice | None = None,
    *,
    technical: TechnicalSignals | None = None,
) -> QueenCouncil:
    source: TechnicalSignalsSource | None = (
        _StaticTechnical(technical) if technical is not None else None
    )
    return QueenCouncil(
        _Static(finances or _finances()), technical=source, voice=voice, clock=lambda: NOW
    )


# --- verdictul CFO-ului (determinist) --------------------------------------------


def test_profitable_account_is_judged_by_blended_cpa_against_the_target() -> None:
    snapshot = build_financial_snapshot(_finances())

    assert snapshot.status == "profitable"
    assert snapshot.spend == Decimal("1020")
    assert snapshot.conversions == 26
    assert snapshot.cpa == Decimal("39.23")
    assert snapshot.target_cpa == Decimal("80")
    assert snapshot.verdict == (
        "Contul e rentabil: CPA-ul e 39,23 RON (26 de conversii din 1020 RON cheltuiți), sub "
        "ținta de 80 RON."
    )
    [ad] = snapshot.ads
    assert (ad.verdict, ad.cpa) == ("profitable", Decimal("68.89"))
    assert snapshot.search is not None
    assert snapshot.search.zero_conversion_terms == 1
    assert snapshot.search.zero_conversion_cost == Decimal("100")


def test_losing_ads_are_named_and_the_account_is_unprofitable() -> None:
    snapshot = build_financial_snapshot(LOSING)

    assert snapshot.status == "unprofitable"
    assert snapshot.verdict.startswith("Contul nu e rentabil: CPA-ul e 175 RON")
    verdicts = {ad.ad_id: (ad.verdict, ad.reason) for ad in snapshot.ads}
    assert verdicts["111"] == ("unprofitable", "CPA 150 RON, peste ținta de 80 RON")
    assert verdicts["222"][0] == "unprofitable"
    assert "fără nicio conversie, peste ținta pentru o conversie (80 RON)" in verdicts["222"][1]


def test_an_ad_below_one_target_of_spend_is_too_early_to_judge() -> None:
    [ad] = build_financial_snapshot(_finances(ads=(_ad(spend="40", conversions=0),))).ads
    assert ad.verdict == "too_early"
    assert ad.reason == "40 RON cheltuiți, încă fără conversii, prea devreme de judecat"


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (NO_MONEY, "Nu există încă nicio cheltuială înregistrată"),
        (
            _finances(ads=(_ad(spend="300", conversions=3),), terms=()),
            "Date insuficiente: 3 conversii din 300 RON cheltuiți, sub pragul de 5 conversii",
        ),
    ],
)
def test_without_enough_conversions_the_cfo_does_not_judge(
    signals: FinancialSignals, expected: str
) -> None:
    snapshot = build_financial_snapshot(signals)

    assert snapshot.status == "insufficient_data"
    assert snapshot.verdict.startswith(expected)
    assert "rentabil:" not in snapshot.verdict


def test_sales_accounts_are_judged_by_roas() -> None:
    signals = _finances(
        ads=(_ad(spend="500", conversions=10, revenue="1500"),), terms=(), objective="sales"
    )
    snapshot = build_financial_snapshot(signals)

    assert snapshot.status == "profitable"
    assert snapshot.roas == Decimal("3.00")
    assert snapshot.verdict.startswith("Contul își acoperă cheltuiala: ROAS 3")
    assert "Marja nu o cunosc" in snapshot.verdict


def test_without_a_target_or_values_the_cfo_says_so() -> None:
    snapshot = build_financial_snapshot(_finances(ads=()))

    assert snapshot.status == "no_benchmark"
    assert "nu pot spune dacă e rentabil" in snapshot.verdict


def test_different_targets_are_weighted_by_spend() -> None:
    ads = (_ad(spend="300", conversions=6, target="60"), _ad("2", spend="100", target="100"))
    snapshot = build_financial_snapshot(_finances(ads=ads, terms=()))

    assert snapshot.target_cpa == Decimal("70.00")
    assert "ținta medie (ponderată cu cheltuiala) de 70 RON" in snapshot.verdict


# --- despre ce e intrebarea ---------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Merită să cresc bugetul?", QuestionTopic("budget")),
        ("Vreau să dublez bugetul pe TikTok", QuestionTopic("budget", "tiktok")),
        ("Ce zici de LinkedIn?", QuestionTopic("channel", "linkedin")),
        ("E rentabilă campania pe Meta?", QuestionTopic("profitability")),
        ("Cât mă costă un client?", QuestionTopic("profitability")),
        ("Cine e publicul meu?", QuestionTopic("audience")),
        ("Cum ar trebui să sune reclamele?", QuestionTopic("creative")),
        ("Salut! Ce părere ai?", QuestionTopic("general")),
        ("Ce faci?", QuestionTopic("general")),
    ],
)
def test_classify_question(question: str, expected: QuestionTopic) -> None:
    assert classify_question(question, active_platforms={"meta", "google"}) == expected


# --- decizia consiliului -------------------------------------------------------------


def test_budget_on_a_profitable_account_grows_only_what_already_works() -> None:
    ruling = rule_on_question(
        QuestionTopic("budget"), _directive(), build_financial_snapshot(_finances())
    )

    assert ruling.decision.startswith("Da, dar controlat")
    assert ruling.cut == []
    assert ruling.approved[0] == (
        f"creșterea treptată a cheltuielilor doar pe ce e deja rentabil («{TECHNICAL_HEADLINE}»), "
        "în plafonul zilnic de 50 RON (peste plafon decide agenția)"
    )


def test_cfo_cuts_creative_ideas_that_need_money_on_a_losing_account() -> None:
    snapshot = build_financial_snapshot(LOSING)
    ruling = rule_on_question(QuestionTopic("budget"), _directive(), snapshot)

    assert ruling.decision == "Nu acum: contul nu e rentabil. Întâi se taie ce pierde bani."
    assert ruling.cut[0] == "creșterea bugetului: contul nu e rentabil"
    assert any(
        "testează-le ca set separat: un test nou consumă buget" in idea for idea in ruling.cut
    )
    # Ce nu costa bani trece si pe un cont pe pierdere.
    approved = " | ".join(ruling.approved)
    assert "oprirea sau refacerea anunțului 222" in approved
    assert "nu îi vorbește clientului ideal și nici nu e rentabilă" in approved


def test_a_profitable_ad_the_queen_wants_rewritten_becomes_an_ab_test() -> None:
    ruling = rule_on_question(
        QuestionTopic("creative"), _directive(), build_financial_snapshot(_finances())
    )

    assert ruling.approved[0].startswith(
        f"rescrierea reclamei «{TECHNICAL_HEADLINE}», dar ca test A/B lângă varianta actuală"
    )
    assert "nu o înlocuim până nu o bate varianta nouă" in ruling.approved[0]


@pytest.mark.parametrize(
    ("finances", "approved"), [(_finances(), True), (LOSING, False)]
)
def test_a_new_channel_is_a_small_test_only_on_a_profitable_account(
    finances: FinancialSignals, approved: bool
) -> None:
    ruling = rule_on_question(
        QuestionTopic("channel", "tiktok"), _directive(), build_financial_snapshot(finances)
    )

    ideas = ruling.approved if approved else ruling.cut
    assert ideas[0].startswith("un test pe TikTok" if approved else "un canal nou (TikTok)")
    assert ruling.decision.startswith("Se poate testa TikTok" if approved else "Nu încă")


# --- garda ---------------------------------------------------------------------------------

_FACTS = "- CPA 39,23 RON, ținta 80 RON. Garanție 12 luni.\n«Merită 200 RON pe zi?»"


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Contul e rentabil, CPA 39,23 RON.", None),
        ("La 200 RON pe zi nu recomandăm încă.", None),  # cifra clientului, repetata
        ("Ai o garanție de 12 luni pe lucrări.", None),
        ("Vei avea 40% mai mulți clienți.", "cifre care nu sunt în date (40)"),
        ("La 200 RON pe zi vei avea 5 clienți în plus.", "cifre care nu sunt în date (5)"),
        ("Am mărit deja bugetul campaniei.", "pretindea o acțiune făcută"),
        ("Vom crește bugetul de luni.", "promitea cheltuieli"),
        ("Îți garantăm mai multe programări.", "garanta rezultate"),
        ("Detalii pe https://exemplu.ro", "linkuri"),
        ("  ", "gol"),
    ],
)
def test_council_texts_cannot_invent_numbers_actions_or_promises(
    text: str, problem: str | None
) -> None:
    found = check_council_text(text, facts=_FACTS)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


# --- consiliul, cap-coada ----------------------------------------------------------------


def test_council_deliberates_then_the_queen_answers() -> None:
    voice = _CouncilVoice()
    reply = _council(voice=voice).evaluate_client_query("Merită să cresc bugetul?", _directive())

    assert reply.source == "llm"
    assert reply.model == "fake/council"
    assert reply.reply == CHAIR_SAYS
    assert reply.fallback_reason is None
    assert reply.topic == "budget"
    assert reply.financial_status == "profitable"
    assert [(o.member, o.source, o.opinion) for o in reply.opinions] == [
        ("strategist", "llm", STRATEGIST_SAYS),
        ("cfo", "llm", CFO_SAYS),
    ]
    assert voice.roles == ["cfo", "chair", "strategist"]
    assert voice.calls[-1][0] == "chair"  # sinteza vine dupa ambele pareri


def test_each_member_sees_only_its_own_facts_and_the_chair_sees_everything() -> None:
    voice = _CouncilVoice()
    _council(voice=voice).evaluate_client_query("Merită să cresc bugetul?", _directive())

    strategist, cfo, chair = voice.prompt("strategist"), voice.prompt("cfo"), voice.prompt("chair")
    question = "«Merită să cresc bugetul?»"
    assert question in strategist and question in cfo and question in chair
    assert "Unghiul de copy propus" in strategist
    assert "Verdict financiar" not in strategist and "Plafonul zilnic" not in strategist
    assert "Verdict financiar (calculat determinist, obligatoriu): Contul e rentabil" in cfo
    assert "Unghiul de copy propus" not in cfo
    for part in (STRATEGIST_SAYS, CFO_SAYS, "DECIZIA CONSILIULUI", "Decizia (obligatorie): Da"):
        assert part in chair


def test_an_inventive_queen_falls_back_to_the_deterministic_ruling() -> None:
    voice = _CouncilVoice({"chair": "Da! Dublează bugetul și vei avea 40% mai mulți clienți."})
    reply = _council(voice=voice).evaluate_client_query("Merită să cresc bugetul?", _directive())

    assert reply.source == "template"
    assert reply.model is None
    assert reply.fallback_reason is not None and "(40)" in reply.fallback_reason
    assert reply.reply.startswith("Da, dar controlat: contul e rentabil")
    assert reply.reply.endswith("Nimic nu se aplică fără aprobarea ta.")
    assert "40%" not in reply.reply


def test_a_failing_member_is_replaced_by_its_deterministic_position() -> None:
    voice = _CouncilVoice(
        {"strategist": "Am schimbat deja textele reclamei."},
        errors={"cfo": RuntimeError("Hugging Face a răspuns 503")},
    )
    reply = _council(voice=voice).evaluate_client_query("Merită să cresc bugetul?", _directive())

    strategist, cfo = reply.opinions
    assert strategist.source == "template"
    assert strategist.fallback_reason is not None
    assert "pretindea o acțiune făcută" in strategist.fallback_reason
    assert strategist.opinion.startswith("Clientul ideal e «Ocupatul pragmatic»")
    assert cfo.source == "template"
    assert cfo.fallback_reason == "Modelul nu a răspuns (RuntimeError) - poziția deterministă."
    assert cfo.opinion.startswith("Contul e rentabil: CPA-ul e 39,23 RON")
    # Presedintele tot delibereaza - pe pozitiile deterministe.
    assert reply.source == "llm"
    assert "Am schimbat deja" not in voice.prompt("chair")


def test_without_a_voice_the_council_answers_deterministically() -> None:
    reply = _council().evaluate_client_query("E rentabilă campania?", _directive())

    assert reply.source == "template"
    assert reply.fallback_reason == (
        "Vocea LLM nu e configurată - răspunsul determinist al consiliului."
    )
    assert reply.reply.startswith("Contul e rentabil: CPA-ul e 39,23 RON")
    assert all(opinion.source == "template" for opinion in reply.opinions)


def test_without_any_data_no_llm_gives_generic_advice() -> None:
    voice = _CouncilVoice()
    directive = _directive(**THIN_DIRECTIVE_SIGNALS)
    reply = _council(NO_MONEY, voice).evaluate_client_query("Cât buget să pun?", directive)

    assert voice.calls == []
    assert reply.source == "template"
    assert reply.directive_status == "insufficient_data"
    assert reply.financial_status == "insufficient_data"
    assert reply.reply.startswith("Încă nu am destule date ca să-ți răspund pe cifre")
    assert "conectează Search Console" in reply.reply


def test_a_member_without_data_is_not_asked() -> None:
    voice = _CouncilVoice()
    reply = _council(NO_MONEY, voice).evaluate_client_query("Cine e publicul meu?", _directive())

    assert voice.roles == ["chair", "strategist"]
    cfo = reply.opinions[1]
    assert cfo.source == "template"
    assert cfo.opinion.startswith("Nu există încă nicio cheltuială înregistrată")


def test_the_llm_never_changes_the_directive() -> None:
    directive = _directive()
    before = directive.model_dump()

    _council(voice=_CouncilVoice()).evaluate_client_query("Merită să cresc bugetul?", directive)
    _council(LOSING, _CouncilVoice()).evaluate_client_query("Și TikTok?", directive)

    assert directive.model_dump() == before


@pytest.mark.parametrize("query", ["", "   \n ", "x" * 1001])
def test_blank_or_huge_questions_are_rejected(query: str) -> None:
    with pytest.raises(ValueError):
        _council().evaluate_client_query(query, _directive())
