"""Vocea CMO a Reginei: LLM-ul doar formuleaza, nu decide.

Un LLM fals (``_FakeVoice``) inlocuieste Hugging Face. Se verifica partea
riscanta: ce primeste modelul, ce i se respinge (cifre inventate, bugete,
linkuri) si ca orice problema duce la mesajul din template, nu la o eroare.
"""

from __future__ import annotations

import pytest

from ppc_agent_server.services.queen_agent import (
    CMO_SYSTEM_PROMPT,
    BrandSignals,
    BrandStrategist,
    BrandStrategyDirective,
    SearchSignal,
    build_cmo_prompt,
    build_directive,
    check_cmo_message,
    template_cmo_message,
)
from tests_server.test_queen_agent import NOW, _signals

FAITHFUL = (
    "Am observat că publicul tău ideal este «Ocupatul pragmatic»: 47% din căutări și 74% "
    "din conversii vin de la oameni care vor să rezolve totul din telefon. Reclama «Schimb "
    "ulei ATF cutie automata» are un CPA de 68,89 RON, sub ținta de 80 RON, dar vorbește "
    "tehnic, pe limba altui public. Am propus rescrierea ei pe timp salvat și zero bătăi de "
    "cap - totul așteaptă aprobarea ta."
)


class _FakeVoice:
    """LLM-ul fals: intoarce ce i se spune si tine minte ce a primit."""

    model = "fake/cmo-model"

    def __init__(self, answer: str = FAITHFUL, *, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.answer


class _StaticSource:
    def __init__(self, signals: BrandSignals) -> None:
        self._signals = signals

    def load(self, client_account_id: int) -> BrandSignals:
        return self._signals


def _queen(voice: _FakeVoice | None, signals: BrandSignals | None = None) -> BrandStrategist:
    return BrandStrategist(_StaticSource(signals or _signals()), voice=voice, clock=lambda: NOW)


def _directive() -> BrandStrategyDirective:
    return build_directive(42, _signals(), generated_at=NOW)


# --- ce primeste modelul ---------------------------------------------------------


def test_prompt_gives_the_cmo_role_and_only_the_directive_facts() -> None:
    directive = _directive()
    system, user = build_cmo_prompt(directive)

    assert system == CMO_SYSTEM_PROMPT
    assert "Senior AI Chief Marketing Officer" in system
    assert "Nu inventa cifre" in system
    assert user.startswith("FAPTE:")
    assert directive.ideal_avatar_profile in user
    assert directive.copywriting_angle is not None
    assert directive.copywriting_angle.summary in user
    for adjustment in directive.targeting_adjustments:
        assert adjustment.suggestion in user
    assert "«Schimb ulei ATF cutie automata»" in user
    assert "68,89 RON" in user
    assert "nimic nu s-a aplicat" in user


# --- ce se accepta de la model ---------------------------------------------------


def test_faithful_llm_message_is_delivered() -> None:
    voice = _FakeVoice()
    message = _queen(voice).generate_cmo_message(42, _directive())

    assert message.source == "llm"
    assert message.model == "fake/cmo-model"
    assert message.message == FAITHFUL
    assert message.fallback_reason is None
    assert message.directive_status == "ok"
    assert len(voice.calls) == 1


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (FAITHFUL + " Estimăm cu 30% mai multe programări.", "cifre care nu sunt în date (30)"),
        ("Am mărit bugetul campaniei Meta ca să ajungem la publicul ideal.", "«buget...»"),
        ("Propunem licitări mai agresive pe «programare online».", "«licit...»"),
        (FAITHFUL + " Detalii: https://exemplu.ro/raport", "linkuri"),
        ("   ", "gol"),
        ("x" * 2000, "prea lung"),
    ],
)
def test_llm_cannot_add_numbers_budgets_or_links(answer: str, reason: str) -> None:
    message = _queen(_FakeVoice(answer)).generate_cmo_message(42, _directive())

    assert message.source == "template"
    assert message.model is None
    assert message.fallback_reason is not None and reason in message.fallback_reason
    assert message.message == template_cmo_message(_directive())


def test_number_formats_are_compared_by_value() -> None:
    _, facts = build_cmo_prompt(_directive())
    assert check_cmo_message("CPA 68.89 RON, ținta 80,00 RON.", facts=facts) is None
    assert check_cmo_message("CPA 69 RON.", facts=facts) is not None


def test_llm_errors_fall_back_to_the_template() -> None:
    voice = _FakeVoice(error=RuntimeError("Hugging Face a răspuns 503"))
    message = _queen(voice).generate_cmo_message(42, _directive())

    assert message.source == "template"
    assert message.fallback_reason == "Modelul nu a răspuns (RuntimeError) - mesaj din template."
    assert "503" not in message.message


def test_without_a_voice_the_template_speaks() -> None:
    message = _queen(None).generate_cmo_message(42, _directive())

    assert message.source == "template"
    assert message.fallback_reason == "Vocea LLM nu e configurată - mesaj din template."


def test_insufficient_data_never_reaches_the_llm() -> None:
    voice = _FakeVoice()
    signals = _signals(searches=[SearchSignal("service cutie automata pret", "paid", 40, 3)])
    queen = _queen(voice, signals)

    directive = queen.evaluate_brand_alignment(42)
    message = queen.generate_cmo_message(42, directive)

    assert voice.calls == []
    assert message.directive_status == "insufficient_data"
    assert message.message.startswith("Încă nu pot contura clientul tău ideal.")


def test_llm_output_never_changes_the_directive() -> None:
    """Separarea: LLM-ul formuleaza; directiva (si orice cifra din ea) ramane neatinsa."""
    directive = _directive()
    before = directive.model_dump()

    _queen(_FakeVoice("Am mărit bugetul cu 500 RON.")).generate_cmo_message(42, directive)
    _queen(_FakeVoice()).generate_cmo_message(42, directive)

    assert directive.model_dump() == before


def test_a_directive_is_only_explained_to_its_own_client() -> None:
    with pytest.raises(ValueError, match="altui client"):
        _queen(_FakeVoice()).generate_cmo_message(7, _directive())


# --- template-ul ------------------------------------------------------------------


def test_template_explains_the_decision_with_the_same_facts() -> None:
    text = template_cmo_message(_directive())

    assert text.startswith("Am analizat căutările și reclamele contului tău.")
    assert "«Ocupatul pragmatic» (47% din căutări și 74% din conversii)" in text
    assert "Reclama «Schimb ulei ATF cutie automata» nu rezonează cu el" in text
    assert "68,89 RON" in text
    assert "ce am propus: schimbă textele din tehnice" in text.lower()
    assert text.endswith("nimic nu se aplică până nu le aprobi tu.")
    # Template-ul trece de propria garda: nicio cifra in afara faptelor.
    _, facts = build_cmo_prompt(_directive())
    assert check_cmo_message(text, facts=facts) is None
