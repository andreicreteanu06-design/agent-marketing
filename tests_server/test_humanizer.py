"""Stratul "humanizer": vocea de consultant senior in prompturi, fara sa slabeasca garzile.

Stilul e doar instructiune pentru model. Se verifica: ca ajunge in toate
prompturile care produc text pentru client, ca vine DUPA regulile anti-halucinatie
(care au prioritate), ca nu aduce exemple de copiat si ca un text scris "uman"
dar cu o cifra inventata sau o actiune pretinsa e respins la fel ca inainte.
"""

from __future__ import annotations

import re

import pytest

from ppc_agent_server.services.council import (
    CHAIR_SYSTEM_PROMPT,
    LANGUAGE_GUARD,
    check_council_text,
)
from ppc_agent_server.services.humanizer import CONSULTANT_VOICE, ai_tells
from ppc_agent_server.services.queen_agent import (
    CMO_SYSTEM_PROMPT,
    build_cmo_prompt,
    build_directive,
    check_cmo_message,
    template_cmo_message,
)
from tests_server.test_queen_agent import NOW, _signals
from tests_server.test_queen_council import (
    LOSING,
    NO_MONEY,
    THIN_DIRECTIVE_SIGNALS,
    _council,
    _CouncilVoice,
    _finances,
)

CLIENT_FACING_PROMPTS = {
    "cmo": (CMO_SYSTEM_PROMPT, "Nu inventa cifre"),
}


@pytest.mark.parametrize("role", sorted(CLIENT_FACING_PROMPTS))
def test_every_client_facing_prompt_speaks_like_a_senior_consultant(role: str) -> None:
    prompt, factual_rule = CLIENT_FACING_PROMPTS[role]

    assert prompt.endswith(CONSULTANT_VOICE)
    # Regulile anti-halucinatie raman primele - stilul vine dupa ele si le cedeaza.
    assert prompt.index(factual_rule) < prompt.index("VOCEA (regulile de mai sus au prioritate")


def test_the_chair_keeps_a_short_language_guard_instead_of_the_long_voice() -> None:
    # Pentru un model de 1,5B, stilul lung al consultantului era zgomot: sinteza are
    # garda ei de limbaj, scurta, dupa reguli.
    assert CONSULTANT_VOICE not in CHAIR_SYSTEM_PROMPT
    assert CHAIR_SYSTEM_PROMPT.endswith(LANGUAGE_GUARD)
    assert len(CHAIR_SYSTEM_PROMPT) < 2000
    for asked in (
        "strict cuvintele și cifrele din pozițiile membrilor",
        "Nu adaugi nicio poveste",
        "Nu te adresezi ție însăți",
        "nu scrii «Regina,»",
        "nu saluți și nu semnezi",
    ):
        assert asked in LANGUAGE_GUARD


def test_the_voice_asks_for_rhythm_active_voice_and_no_ai_speak() -> None:
    for asked in (
        "director de marketing",
        "la o cafea",
        "profesionist, direct, asertiv și empatic",
        "propoziții foarte scurte, percutante, de două până la cinci cuvinte",
        "Evită structurile simetrice",
        "Fără scuze și fără politețuri de umplutură",
        "Diateza activă",
        "«nu doar X, ci și Y»",
        "Fără liniuțe",
        "crucial",
        "peisaj",
        "a naviga",
        "aprofundare",
        "tapiserie",
        "a rezona / rezonare",
        "în concluzie",
        "«Să analizăm»",
        "«Este important să notăm»",
        "«Sper că te ajută»",
        "«De asemenea,»",
    ):
        assert asked in CONSULTANT_VOICE


def test_the_voice_gives_the_model_nothing_to_copy_as_a_fact() -> None:
    """Fara cifre si fara fraze-exemplu despre reclame: un model mic le-ar repeta ca fapte."""
    assert re.search(r"\d", CONSULTANT_VOICE) is None
    assert "RON" not in CONSULTANT_VOICE and "CPA" not in CONSULTANT_VOICE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Desigur! Este crucial să navigăm acest peisaj dinamic.", ["crucial", "peisaj"]),
        ("Am văzut cifrele. Reclama aduce clienți. De asemenea, sper că te ajută.", ["De"]),
        ("ESENȚIAL e să deblocăm potențialul maxim.", ["esențial", "a debloca"]),
    ],
)
def test_ai_tells_are_recognised_without_diacritics_or_case(
    text: str, expected: list[str]
) -> None:
    found = ai_tells(text)
    for label in expected:
        assert any(item.startswith(label) for item in found), found


def test_plain_consultant_prose_has_no_tells() -> None:
    text = (
        "Da, poți crește bugetul. Contul e rentabil: CPA-ul e 39,23 RON, sub ținta de 80 RON, "
        "deci fiecare leu în plus merge pe ce aduce deja clienți. Reclama tehnică o rescriem, "
        "dar o lăsăm să ruleze până o bate varianta nouă."
    )
    assert ai_tells(text) == []


def test_deterministic_fallbacks_already_speak_without_ai_tells() -> None:
    directive = build_directive(42, _signals(), generated_at=NOW)
    thin = build_directive(42, _signals(**THIN_DIRECTIVE_SIGNALS), generated_at=NOW)
    texts = [template_cmo_message(directive), template_cmo_message(thin)]
    for finances in (_finances(), LOSING, NO_MONEY):
        for context in (directive, thin):
            for question in ("Merită să cresc bugetul?", "Ce zici de TikTok?", "Cine e publicul?"):
                reply = _council(finances).evaluate_client_query(question, context)
                texts.append(reply.reply)
                texts.extend(opinion.opinion for opinion in reply.opinions)
    assert [(text[:60], ai_tells(text)) for text in texts if ai_tells(text)] == []


# --- garzile nu s-au relaxat ---------------------------------------------------------

HUMAN_BUT_INVENTIVE = [
    ("Da, crește bugetul. Cu 30% mai mult, programările cresc și ele.", "(30)"),
    ("Am mărit deja bugetul pe Meta. Merită, iar tu vei vedea asta repede.", "pretindea"),
    ("Hai să fim direcți: îți garantăm mai multe programări.", "garanta"),
]


@pytest.mark.parametrize(("text", "problem"), HUMAN_BUT_INVENTIVE)
def test_a_human_tone_does_not_get_past_the_council_guard(text: str, problem: str) -> None:
    facts = "- Contul e rentabil: CPA-ul e 39,23 RON, sub ținta de 80 RON."
    found = check_council_text(text, facts=facts)
    assert found is not None and problem in found


def test_a_human_tone_does_not_get_past_the_cmo_guard() -> None:
    _, facts = build_cmo_prompt(build_directive(42, _signals(), generated_at=NOW))
    text = "Pe scurt: publicul tău vrea viteză. Îți aduc cu 40% mai mulți clienți."
    problem = check_cmo_message(text, facts=facts)
    assert problem is not None and "(40)" in problem


def test_a_humanized_chair_that_invents_still_falls_back() -> None:
    voice = _CouncilVoice(
        {"chair": "Da. Crește bugetul acum, iar în două săptămâni vei avea 25 de clienți în plus."}
    )
    directive = build_directive(42, _signals(), generated_at=NOW)
    reply = _council(voice=voice).evaluate_client_query("Merită să cresc bugetul?", directive)

    assert reply.source == "template"
    assert reply.fallback_reason is not None and "(25)" in reply.fallback_reason
