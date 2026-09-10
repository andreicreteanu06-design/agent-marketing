"""Teste deterministe pentru AdCopyGenerator, check_google_limits si retry."""

from __future__ import annotations

import pytest

from ppc_agent.copywriter.engine import (
    HEADLINE_LIMIT,
    AdCopyGenerator,
    check_google_limits,
)
from ppc_agent.copywriter.llm import BaseLLMClient, MockLLMClient
from ppc_agent.copywriter.models import AdCopy, CopySpec, char_count
from ppc_agent.errors import AdsLimitError, CopywriterError
from ppc_agent.texttools import contains_phrase

_USP = "Diagnoza in 30 de minute, pret fix, verdict clar pe loc"


def _generator() -> AdCopyGenerator:
    return AdCopyGenerator(MockLLMClient())


@pytest.mark.parametrize("trigger", ["pas", "status", "fomo", "aida"])
def test_output_shape_and_limits_per_framework(trigger: str) -> None:
    result = _generator().generate_emotional_copy(_USP, "cutie viteze", trigger)
    assert set(result) == {"headline_1", "headline_2", "description"}
    assert char_count(result["headline_1"]) <= 30
    assert char_count(result["headline_2"]) <= 30
    assert char_count(result["description"]) <= 90


@pytest.mark.parametrize("trigger", ["pas", "status", "fomo", "aida"])
def test_keyword_is_forced_into_a_headline(trigger: str) -> None:
    result = _generator().generate_emotional_copy(_USP, "reparatii frigidere", trigger)
    in_h1 = contains_phrase(result["headline_1"], "reparatii frigidere")
    in_h2 = contains_phrase(result["headline_2"], "reparatii frigidere")
    assert in_h1 or in_h2


def test_generation_is_deterministic() -> None:
    first = _generator().generate_emotional_copy(_USP, "curs excel", "fomo")
    second = _generator().generate_emotional_copy(_USP, "curs excel", "fomo")
    assert first == second


def test_different_triggers_produce_different_copy() -> None:
    gen = _generator()
    pas = gen.generate_emotional_copy(_USP, "cutie viteze", "frica")
    aida = gen.generate_emotional_copy(_USP, "cutie viteze", "aida")
    assert pas != aida


def test_check_google_limits_raises_on_long_headline() -> None:
    ad = AdCopy(
        headline_1="Acesta este un titlu mult prea lung pentru Google Ads sigur",
        headline_2="ok",
        description="ok",
    )
    with pytest.raises(AdsLimitError) as excinfo:
        check_google_limits(ad)
    assert excinfo.value.field == "headline_1"
    assert excinfo.value.limit == HEADLINE_LIMIT


def test_check_google_limits_raises_on_long_description() -> None:
    ad = AdCopy(
        headline_1="ok",
        headline_2="ok",
        description="x" * 91,
    )
    with pytest.raises(AdsLimitError) as excinfo:
        check_google_limits(ad)
    assert excinfo.value.field == "description"


def test_keyword_longer_than_headline_limit_fails_clearly() -> None:
    with pytest.raises(CopywriterError):
        _generator().generate_emotional_copy(
            _USP, "reparatii cutii de viteze automate pentru masini germane", "pas"
        )


class _OverLimitClient(BaseLLMClient):
    """Client de test: intai peste limita, apoi respecta limitele la tighten>=1."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, spec: CopySpec) -> AdCopy:
        self.calls += 1
        if spec.tighten == 0:
            return AdCopy(
                headline_1="Titlu enorm care depaseste clar limita Google",
                headline_2="alt titlu mult prea lung pentru un anunt real",
                description="d" * 120,
            )
        return AdCopy(
            headline_1=spec.target_keyword,
            headline_2="Scurt si la obiect",
            description="Text conform, sub nouazeci de caractere, complet.",
        )


class _AlwaysOverClient(BaseLLMClient):
    def generate(self, spec: CopySpec) -> AdCopy:
        return AdCopy(headline_1="x" * 40, headline_2="y" * 40, description="z" * 200)


def test_engine_retries_then_succeeds() -> None:
    client = _OverLimitClient()
    generator = AdCopyGenerator(client)
    result = generator.generate_emotional_copy(_USP, "curs excel", "fomo")
    assert client.calls >= 2
    assert char_count(result["headline_1"]) <= 30
    assert char_count(result["description"]) <= 90


def test_engine_fails_gracefully_after_max_retries() -> None:
    generator = AdCopyGenerator(_AlwaysOverClient())
    with pytest.raises(AdsLimitError):
        generator.generate_emotional_copy(_USP, "curs excel", "fomo")


def test_system_prompt_injects_framework() -> None:
    from ppc_agent.copywriter.engine import build_system_prompt
    from ppc_agent.copywriter.swipe import default_swipe_path, load_swipe_file, retrieve_framework

    framework = retrieve_framework(load_swipe_file(default_swipe_path()), "fomo")
    prompt = build_system_prompt(framework, 30, 90)
    assert framework.name in prompt
    assert "maxim 30 caractere" in prompt
    assert framework.example_ad.headline_1 in prompt
