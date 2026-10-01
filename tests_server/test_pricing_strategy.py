"""Strategia de pret a consiliului: CPO-ul (3 niveluri, Free -> platit) si CFO-ul (valoare,
niciodata cost-plus), cu sectiunile din framework in raspuns.

Pe acelasi service de cutii automate ca restul testelor consiliului; fara LLM.
"""

from __future__ import annotations

import pytest

from ppc_agent_server.services.council import classify_question
from ppc_agent_server.services.queen_agent import SearchSignal
from tests_server.test_cpo import MISPOSITIONED_SEARCHES
from tests_server.test_queen_council import (
    LOSING,
    NO_MONEY,
    THIN_DIRECTIVE_SIGNALS,
    _ad,
    _council,
    _CouncilVoice,
    _directive,
    _finances,
)

PRICE_QUESTION = "Ce preț să pun la noul pachet de revizie?"
#: Doar vanatori de pret, care si cumpara: clientul ideal e «Vânătorul de preț».
PRICE_BUYERS = [
    SearchSignal("service cutie automata pret", "paid", 1500, 90, 12.0),
    SearchSignal("schimb ulei cutie automata pret", "organic", 1200, 40),
    SearchSignal("cat costa revizia cutiei automate", "paid", 800, 60, 6.0),
]


@pytest.mark.parametrize(
    ("question", "pricing"),
    [
        ("Ce preț să pun la noul pachet de revizie?", True),
        ("Vreau să lansez un serviciu nou, cum îl împachetez?", True),
        ("Merită o reducere de Black Friday?", True),
        ("Cum îmbunătățesc oferta?", True),
        ("Merită să cresc bugetul?", False),
        ("Cine e publicul meu?", False),
    ],
)
def test_intrebarile_de_pret_si_oferta_sunt_recunoscute(question: str, pricing: bool) -> None:
    assert classify_question(question, active_platforms=set()).about_pricing is pricing


def test_pretul_click_ului_nu_e_o_intrebare_de_pret_al_ofertei() -> None:
    topic = classify_question("De ce a crescut prețul pe click?", active_platforms=set())
    assert topic.about_cpc
    assert not topic.about_pricing


def test_raspunsul_are_cele_trei_sectiuni_din_framework() -> None:
    reply = _council().evaluate_client_query(PRICE_QUESTION, _directive())

    sections = reply.reply.split("\n\n")[-1].splitlines()
    assert [line.split(":", 1)[0] for line in sections] == [
        "Recommended Pricing Model",
        "Value Metric",
        "Competitive Position",
    ]
    assert reply.ruling.pricing is not None
    assert "Starter, Pro, Business" in sections[0]


def test_cfo_ul_cere_pret_pe_valoare_si_un_value_metric() -> None:
    reply = _council().evaluate_client_query(PRICE_QUESTION, _directive())

    cfo = next(opinion for opinion in reply.opinions if opinion.member == "cfo")
    assert "Prețul nu se stabilește pe cost (cost-plus): reflectă valoarea livrată." in cfo.opinion
    assert "Value Metric: serviciul complet, de la preluare la predare." in cfo.opinion


def test_cfo_ul_ancoreaza_pretul_in_valoarea_unei_comenzi() -> None:
    """Magazin (``sales``) cu venit atribuit: metrica e comanda, ancora e valoarea ei medie."""
    shop = _finances(
        ads=(_ad(spend="600", conversions=10, revenue="2400"),), terms=(), objective="sales"
    )
    reply = _council(shop).evaluate_client_query(PRICE_QUESTION, _directive())

    assert reply.ruling.pricing is not None
    assert reply.ruling.pricing.value_metric == "comanda, după valoarea coșului"
    cfo = next(opinion for opinion in reply.opinions if opinion.member == "cfo")
    assert "O conversie aduce în medie 240 RON: de acolo pornește prețul." in cfo.opinion


def test_cpo_ul_impacheteaza_pe_trei_niveluri_cu_pro_cea_mai_buna_valoare() -> None:
    reply = _council().evaluate_client_query(PRICE_QUESTION, _directive())

    cpo = next(opinion for opinion in reply.opinions if opinion.member == "cpo")
    assert "Starter:" in cpo.opinion
    assert "Pro, pentru «Ocupatul pragmatic»" in cpo.opinion
    assert "E cea mai bună valoare dintre cele trei." in cpo.opinion
    assert "Business:" in cpo.opinion and "preț minim afișat" in cpo.opinion
    # «Ocupatul pragmatic» nu are o intrare gratuita care sa nu coste o lucrare intreaga.
    assert "Fără nivel gratuit" in cpo.opinion
    assert "De la Starter la Pro trece când" in cpo.opinion


def test_o_intrare_gratuita_are_un_declansator_concret_si_un_prag() -> None:
    reply = _council().evaluate_client_query(
        PRICE_QUESTION, _directive(searches=MISPOSITIONED_SEARCHES)
    )

    pricing = reply.ruling.pricing
    assert pricing is not None
    # Cumpara «Scepticul care vrea garanții»: el da nivelul Pro, metrica si gratuitul.
    assert pricing.value_metric == "lucrarea cu garanție scrisă"
    assert "Free -> plătit: clientul vede garanția scrisă" in pricing.upgrade_trigger
    assert "2-5%" in pricing.upgrade_trigger


@pytest.mark.parametrize(
    ("finances", "directive_kwargs", "position"),
    [
        (LOSING, {}, "Parity"),  # nerentabil: nici Value, nici Premium
        (None, {}, "Premium"),  # rentabil, cu dovada: programarea online
        (None, {"searches": PRICE_BUYERS}, "Value"),  # rentabil, cumpara pe pret
        (None, {"searches": MISPOSITIONED_SEARCHES}, "Premium"),  # cumpara pe garantie
    ],
)
def test_pozitia_competitiva_se_alege_din_cine_cumpara_si_din_bani(
    finances: object, directive_kwargs: dict[str, object], position: str
) -> None:
    council = _council(finances) if finances is not None else _council()  # type: ignore[arg-type]
    reply = council.evaluate_client_query(PRICE_QUESTION, _directive(**directive_kwargs))

    assert reply.ruling.pricing is not None
    assert reply.ruling.pricing.position == position
    assert f"Competitive Position: {position} - " in reply.reply
    assert "Prețurile concurenților nu le am" in reply.reply


def test_nerentabil_spune_cand_se_poate_iesi_din_parity() -> None:
    reply = _council(LOSING).evaluate_client_query(PRICE_QUESTION, _directive())

    assert reply.ruling.pricing is not None
    assert reply.ruling.pricing.position_reason.startswith(
        "la prețul pieței până când CPA-ul contului coboară sub ținta de 80 RON"
    )


def test_o_intrebare_care_nu_e_despre_pret_nu_primeste_sectiunile() -> None:
    reply = _council().evaluate_client_query("Merită să cresc bugetul?", _directive())

    assert reply.ruling.pricing is None
    assert "Recommended Pricing Model" not in reply.reply
    cfo = next(opinion for opinion in reply.opinions if opinion.member == "cfo")
    assert "cost-plus" not in cfo.opinion


def test_fara_date_nu_da_un_sfat_generic_de_pret() -> None:
    reply = _council(NO_MONEY).evaluate_client_query(
        PRICE_QUESTION, _directive(**THIN_DIRECTIVE_SIGNALS)
    )

    assert reply.ruling.pricing is None
    assert "Recommended Pricing Model" not in reply.reply


def test_sectiunile_raman_exacte_si_dupa_sinteza_llm() -> None:
    """Sinteza nu are voie sa copieze etichete: sectiunile se lipesc dupa ea, neschimbate."""
    voice = _CouncilVoice()
    reply = _council(voice=voice).evaluate_client_query(PRICE_QUESTION, _directive())

    assert reply.ruling.pricing is not None
    assert reply.reply.endswith(reply.ruling.pricing.sections())
    assert "Recommended Pricing Model" not in voice.prompt("chair")
