"""CPO-ul (Chief Product Officer): apara oferta si potrivirea ei cu piata.

Al cincilea membru al consiliului Reginei (``council.py``). Ceilalti judeca
mesajul (Regina), banii (CFO-ul), infrastructura (Tehnicianul) si piata
(Researcher-ul); CPO-ul judeca OFERTA - ce vinde clientul si cui. Cand CFO-ul
gaseste contul nerentabil, desparte doua cauze care arata la fel in cifre:

- **mesajul**: reclamele nu ii vorbesc clientului ideal -> oferta ramane, se
  rescrie mesajul (CPO-ul o apara);
- **oferta**: reclamele ii vorbesc deja clientului ideal si tot pierd bani ->
  oferta nu convinge. Pivotarea se propune doar spre un semnal real: durerea care
  creste in piata (Researcher-ul, doar din date masurate) sau segmentul
  care cumpara mai usor decat cauta. Fara semnal, oferta se testeaza, nu se schimba.

Framework-uri de produs (idei din menkesu/awesome-pm-skills, niciun rand copiat):

- **Positioning** (April Dunford): pornesti de la clientii care cumpara cel mai
  usor, nu de la cei care cauta cel mai mult. Indicele de potrivire al unui
  segment = cota lui din conversii / cota din cautari; de la 1,25, cu cel putin
  20% din conversii, segmentul e "best-fit". Daca nu e clientul ideal caruia ii
  vorbesc reclamele, pozitionarea se poate ascuti.
- **Strategic storytelling**: povestea ofertei in trei timpi - problema (durerea
  profilului), promisiunea (dorinta lui), dovada (ce il convinge).
- **Arhitectura alegerii** (Iyengar, choice overload): peste 3 pachete, oamenii amana
  alegerea - CPO-ul cere cel mult 3, clare; fara garantie, propune inversarea riscului
  (garantie, audit sau consultatie gratuita), dupa bariera dominanta a CMO-ului. Faptele
  vin din interviul clientului (``avatar_builder.OfferFacts``), nu din cont.
- **RICE** (Intercom): mutarile de oferta, ordonate dupa Reach x Impact x
  Confidence / Effort. Reach = procentul din conversii atins (din cautari, cat timp
  conversiile nu ajung), Impact pe scara 0,25-3, Confidence din cat de solide sunt
  datele, Effort in saptamani.

Impactul si efortul fiecarei mutari le noteaza Jev (Sistemul 1, ``llm_client.py``),
intr-o singura cerere: alege un NIVEL pe fiecare scara, iar valoarea nivelului si
formula RICE raman in cod. Fara Jev, cand pica sau cand nu e sigur (``confidence``
sub prag), raman estimarile fixe pe tip de mutare. Reach-ul si Confidence-ul vin
mereu din date. In rest, modul e pur si determinist: fara DB, fara LLM generativ;
pozitia CPO-ului e ``ProductDirective.summary``, iar sinteza Reginei (``council.py``)
doar o formuleaza.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from ppc_agent_server.services.llm_client import MIN_CONFIDENCE, JsonValue, Score, ScoreAnswer
from ppc_agent_server.services.propensity import MAX_OPTIONS
from ppc_agent_server.services.queen_agent import (
    _BY_KEY,
    AdAlignment,
    AvatarSegment,
    BrandStrategyDirective,
    _quote,
)
from ppc_agent_server.services.researcher import MarketDirective, PainSignal
from ppc_agent_server.services.ro_format import count as _count
from ppc_agent_server.services.ro_format import percent as _percent
from ppc_agent_server.services.ro_format import ron as _ron

logger = logging.getLogger("ppc_agent_server.services.cpo")

OfferStatus = Literal["fit", "message_gap", "positioning_gap", "offer_gap", "pivot", "unknown"]
MoveKind = Literal["pivot", "reposition", "offer_test", "message", "simplify", "risk_reversal"]
#: Cine a estimat impactul si efortul unei mutari: Jev sau tabelul fix.
RiceEstimate = Literal["jev", "fixed"]

#: Un segment e "best-fit" cand cumpara de atatea ori mai usor decat cauta...
FIT_INDEX_MIN = 1.25
#: ...si aduce cel putin atat din conversii (sub, e zgomot).
FIT_MIN_BUYERS = 0.2
#: Impactul (RICE: 3 masiv, 2 mare, 1 mediu, 0,5 mic) si efortul (saptamani), pe mutare -
#: estimarile fixe, cand Jev nu e configurat, pica sau nu e sigur.
# ponytail: estimari fixe pe tip de mutare; calibreaza-le din rezultatele propunerilor aplicate.
_RICE: dict[MoveKind, tuple[float, float]] = {
    "pivot": (3.0, 4.0),
    "reposition": (2.0, 2.0),
    "offer_test": (2.0, 1.0),
    "message": (1.0, 0.5),
    "simplify": (2.0, 1.0),
    "risk_reversal": (2.0, 0.5),
}
#: Cat de sigure sunt mutarile de arhitectura a alegerii: pleaca din ce a spus clientul.
CHOICE_CONFIDENCE = 0.8

# Intrebarile pentru Jev: in engleza (acolo e cel mai precis), cu nivelurile in ordine,
# fiecare cu valoarea lui RICE. Jev alege nivelul; valoarea si formula raman in cod.
#: Impactul pe fiecare client atins (scara Intercom: 0,25 minim ... 3 masiv).
IMPACT_LEVELS: tuple[tuple[str, float], ...] = (
    ("Minimal: customers it reaches would barely notice the change", 0.25),
    ("Low: makes the offer slightly more convincing", 0.5),
    ("Medium: makes the offer clearly more convincing for the customers it reaches", 1.0),
    ("High: changes the main reason these customers would buy", 2.0),
    ("Massive: changes what the offer means to these customers", 3.0),
)
#: Efortul, in saptamani de lucru (aceleasi trepte ca estimarile fixe).
EFFORT_LEVELS: tuple[tuple[str, float], ...] = (
    ("A few days: rewriting ad texts and headlines", 0.5),
    ("About a week: new ads or a new section on the landing page", 1.0),
    ("About two weeks: new creatives, landing page changes and campaign setup", 2.0),
    ("A month or more: reworking the offer, the pricing or the service itself", 4.0),
)
_IMPACT_QUESTION = (
    "How much would `moves[{index}]` raise the chance that a customer it reaches buys? Judge "
    "the effect on each customer it reaches, not how many customers it reaches."
)
_EFFORT_QUESTION = (
    "How much work would a small marketing agency need before `moves[{index}]` can go live?"
)
#: Ce fel de mutare e, pentru Jev (textul mutarii, in romana, vine alaturi).
_MOVE_TYPES: dict[MoveKind, str] = {
    "pivot": "pivot the offer toward a new angle",
    "reposition": "reposition the offer for another customer segment",
    "offer_test": "test the current offer with its strongest proof in front",
    "message": "rewrite the ads so they speak to the ideal customer",
    "simplify": "cut the offer down to at most three clear packages",
    "risk_reversal": "add a guarantee or a free first step that removes the buyer's risk",
}
#: Inversarea riscului potrivita barierei dominante (CMO).
_RISK_REVERSALS: dict[str, str] = {
    "lack_of_trust": "un audit sau o primă consultație gratuită, ca să te cunoască fără risc",
    "perceived_risk": "o garanție scrisă pe rezultat",
    "price_uncertainty": "prețul fix, scris dinainte, fără costuri ascunse",
}
_DEFAULT_REVERSAL = "o garanție scrisă sau o primă consultație gratuită"


class RiceScorer(Protocol):
    """Sistemul 1 (``llm_client.LLMRouter``): mai multe scari pe acelasi ``state``."""

    def jev_score(
        self, state: JsonValue, questions: Mapping[str, Score]
    ) -> dict[str, ScoreAnswer]: ...


class OfferMove(BaseModel):
    """O mutare de oferta, cu scorul RICE."""

    kind: MoveKind
    text: str
    #: Procentul din conversii atins (din cautari, fara conversii destule), 0-100.
    reach: int
    impact: float
    confidence: float
    #: Saptamani de lucru.
    effort: float
    rice: int
    #: Cine a estimat impactul si efortul: Jev (Sistemul 1) sau tabelul fix.
    estimated_by: RiceEstimate = "fixed"


class ProductDirective(BaseModel):
    """Verdictul CPO-ului pe oferta - calculat determinist."""

    client_account_id: int
    status: OfferStatus
    #: CFO-ul a gasit CPA-ul peste tinta (pe cifre de incredere): CPO-ul a judecat oferta.
    cpa_alarm: bool
    #: Verdictul pe oferta, incepe mereu cu "Oferta ...".
    verdict: str
    #: Cui (sau despre ce) trebuie sa vorbeasca oferta; ``None`` fara client ideal.
    focus: str | None
    #: Segmentul care cumpara cel mai usor, cand e altul decat clientul ideal.
    best_fit: str | None
    positioning: str
    story: str
    #: Mutarile, ordonate dupa RICE.
    moves: list[OfferMove]
    summary: str
    generated_at: datetime
    #: Pachetele si garantia (choice overload, inversarea riscului); ``None`` = nu stim oferta.
    choice_architecture: str | None = None


def _number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def best_fit_segment(directive: BrandStrategyDirective) -> AvatarSegment | None:
    """Segmentul care cumpara cel mai usor fata de cat cauta (Dunford: best-fit customers)."""
    fits = [
        segment
        for segment in directive.segments
        if segment.buyer_share is not None
        and segment.buyer_share >= FIT_MIN_BUYERS
        and segment.demand_share > 0
    ]
    best = max(
        fits,
        key=lambda s: ((s.buyer_share or 0) / s.demand_share, s.buyer_share or 0),
        default=None,
    )
    if best is None or (best.buyer_share or 0) / best.demand_share < FIT_INDEX_MIN:
        return None
    return best


def _shares(segment: AvatarSegment) -> str:
    return (
        f"{_percent(segment.buyer_share or 0)} din conversii la "
        f"{_percent(segment.demand_share)} din căutări"
    )


def _reach(segment: AvatarSegment) -> float:
    """Pe cine atinge o mutare: cumparatorii segmentului; cautatorii, fara conversii destule."""
    return segment.buyer_share if segment.buyer_share is not None else segment.demand_share


def _losing(ad: AdAlignment, avatar: str) -> str:
    assert ad.cpa is not None and ad.target_cpa is not None
    return (
        f"reclama «{ad.headline}» îi vorbește deja lui «{avatar}» și tot pierde bani "
        f"(CPA {_ron(ad.cpa)} RON, peste ținta de {_ron(ad.target_cpa)} RON)"
    )


def _rice(reach: int, impact: float, confidence: float, effort: float) -> int:
    return round(reach * impact * confidence / effort)


def _move(kind: MoveKind, text: str, reach: float, confidence: float) -> OfferMove:
    impact, effort = _RICE[kind]
    points = round(reach * 100)
    return OfferMove(
        kind=kind,
        text=text,
        reach=points,
        impact=impact,
        confidence=confidence,
        effort=effort,
        rice=_rice(points, impact, confidence, effort),
    )


def _level_value(
    answer: ScoreAnswer | None, levels: tuple[tuple[str, float], ...]
) -> float | None:
    """Valoarea nivelului ales de Jev; ``None`` cand raspunsul lipseste sau e nesigur."""
    if answer is None or answer.confidence < MIN_CONFIDENCE or len(answer.legend) != len(levels):
        return None
    return levels[answer.level][1]


def _scored_by_jev(moves: list[OfferMove], scorer: RiceScorer) -> list[OfferMove]:
    """Impactul si efortul mutarilor, notate de Jev intr-o singura cerere.

    O mutare ia estimarea lui Jev doar cand ambele scari au trecut pragul de
    incredere; altfel - sau cand Jev pica - ramane estimarea fixa.
    """
    state: JsonValue = {
        "moves": [{"type": _MOVE_TYPES[move.kind], "description": move.text} for move in moves]
    }
    impact_levels = tuple(level for level, _ in IMPACT_LEVELS)
    effort_levels = tuple(level for level, _ in EFFORT_LEVELS)
    questions: dict[str, Score] = {}
    for index in range(len(moves)):
        questions[f"impact_{index}"] = Score(_IMPACT_QUESTION.format(index=index), impact_levels)
        questions[f"effort_{index}"] = Score(_EFFORT_QUESTION.format(index=index), effort_levels)
    try:
        answers = scorer.jev_score(state, questions)
    except Exception:  # Jev e un plus: fara el, raman estimarile fixe
        logger.warning("[CPO] Jev n-a notat mutările - rămân estimările fixe", exc_info=True)
        return moves
    scored: list[OfferMove] = []
    for index, move in enumerate(moves):
        impact = _level_value(answers.get(f"impact_{index}"), IMPACT_LEVELS)
        effort = _level_value(answers.get(f"effort_{index}"), EFFORT_LEVELS)
        if impact is None or effort is None:
            scored.append(move)
            continue
        scored.append(
            move.model_copy(
                update={
                    "impact": impact,
                    "effort": effort,
                    "rice": _rice(move.reach, impact, move.confidence, effort),
                    "estimated_by": "jev",
                }
            )
        )
    return scored


def _choice_architecture(directive: BrandStrategyDirective) -> tuple[str | None, list[OfferMove]]:
    """Cate pachete si ce garantie vede clientul: verdictul si mutarile (cel mult 3, garantie)."""
    offer = directive.offer
    if offer is None:
        return None, []
    sentences: list[str] = []
    moves: list[OfferMove] = []
    if offer.options is not None and offer.options > MAX_OPTIONS:
        sentences.append(
            f"{offer.options} pachete sunt prea multe: peste {MAX_OPTIONS}, clientul amână "
            f"alegerea. Cel mult {MAX_OPTIONS}, clare, cu unul recomandat."
        )
        moves.append(
            _move(
                "simplify",
                f"reducerea ofertei la cel mult {MAX_OPTIONS} pachete clare (acum {offer.options})",
                1.0,
                CHOICE_CONFIDENCE,
            )
        )
    elif offer.options is not None:
        many = "un singur pachet" if offer.options == 1 else _count(offer.options, "pachete")
        sentences.append(f"{many[:1].upper()}{many[1:]}: alegerea e ușoară.")
    if offer.risk_reversal:
        sentences.append(f"Garanția există («{offer.risk_reversal}»): pune-o în prim-plan.")
    elif offer.risk_reversal is not None:
        experiment = directive.experiment
        reversal = _RISK_REVERSALS.get(experiment.barrier if experiment else "", _DEFAULT_REVERSAL)
        sentences.append(f"Lipsește inversarea riscului: propun {reversal}.")
        moves.append(
            _move("risk_reversal", f"inversarea riscului: {reversal}", 1.0, CHOICE_CONFIDENCE)
        )
    verdict = "Arhitectura alegerii: " + " ".join(sentences) if sentences else None
    return verdict, moves


def evaluate_offer(
    directive: BrandStrategyDirective,
    *,
    unprofitable: bool,
    market: MarketDirective | None = None,
    generated_at: datetime,
    scorer: RiceScorer | None = None,
) -> ProductDirective:
    """Verdictul CPO-ului pe oferta.

    ``unprofitable`` = CFO-ul a gasit contul nerentabil pe cifre de incredere (cu
    tracking-ul picat, cifrele nu declanseaza nicio pivotare). Piata intra doar
    din surse reale; concurentii gasiti pe web intra doar in pozitionare.
    ``scorer`` = Jev, pentru impactul si efortul mutarilor; ``None`` = estimarile fixe.
    """
    avatar = directive.avatar
    choice, choice_moves = _choice_architecture(directive)
    if directive.status != "ok" or avatar is None:
        unknown = (
            "Oferta nu se poate judeca încă: lipsește clientul ideal (prea puține căutări "
            "atribuite)."
        )
        if scorer is not None and choice_moves:
            choice_moves = _scored_by_jev(choice_moves, scorer)
        choice_moves.sort(key=lambda move: -move.rice)
        summary = f"{unknown} {choice}" if choice else unknown
        if choice_moves:
            summary += f" Prioritatea (RICE): {choice_moves[0].text} (scor {choice_moves[0].rice})."
        return ProductDirective(
            client_account_id=directive.client_account_id,
            status="unknown",
            cpa_alarm=unprofitable,
            verdict=unknown,
            focus=None,
            best_fit=None,
            positioning="",
            story="",
            moves=choice_moves,
            summary=summary,
            generated_at=generated_at,
            choice_architecture=choice,
        )

    own = next(segment for segment in directive.segments if segment.key == avatar.key)
    confidence = 0.8 if own.buyer_share is not None else 0.5
    best = best_fit_segment(directive)
    gap = best if best is not None and best.key != avatar.key else None
    pain: PainSignal | None = None
    if market is not None and market.social_sentiment.rising:
        pain = market.social_sentiment.rising[0]
    misaligned = directive.misaligned_ads
    losing = [
        ad
        for ad in directive.ad_alignment
        if ad.avatar_stance == "supportive"
        and ad.cpa is not None
        and ad.target_cpa is not None
        and ad.cpa > ad.target_cpa
    ]

    status: OfferStatus
    target = gap or own
    about = _BY_KEY[target.key].voice
    moves: list[OfferMove] = []
    if unprofitable and losing and (pain is not None or gap is not None):
        status = "pivot"
        if pain is not None:
            focus = pain.theme
            about = f"«{pain.theme}», ce caută piața acum"
            direction = (
                f"Piața caută acum «{pain.theme}» (+{_percent(pain.growth)}, după Researcher): "
                "acolo mutăm unghiul ofertei."
            )
        else:
            assert gap is not None
            focus = gap.name
            direction = (
                f"Cumpără mai ușor «{gap.name}»: {_shares(gap)}. Acolo mutăm unghiul ofertei."
            )
        verdict = (
            f"Oferta trebuie pivotată: {_losing(losing[0], avatar.name)}, deci nu mesajul e "
            f"problema. {direction}"
        )
        moves.append(
            _move("pivot", f"pivotarea unghiului ofertei spre «{focus}»", 1.0, confidence)
        )
    elif unprofitable and losing:
        status = "offer_gap"
        focus = avatar.name
        proof = _BY_KEY[avatar.key].proof_points[0]
        verdict = (
            f"Oferta e sub semnul întrebării: {_losing(losing[0], avatar.name)}. Nu am încă un "
            f"semnal din piață spre care să pivotăm, deci o testăm, nu o schimbăm: {proof}, "
            "în prim-plan."
        )
        moves.append(
            _move(
                "offer_test",
                f"testarea ofertei pentru «{avatar.name}», cu {proof} în prim-plan",
                _reach(own),
                confidence,
            )
        )
    elif unprofitable and misaligned:
        status = "message_gap"
        focus = avatar.name
        headlines = [ad.headline for ad in misaligned[:2]]
        who = (
            f"reclama {_quote(headlines)} nu îi vorbește"
            if len(headlines) == 1
            else f"reclamele {_quote(headlines)} nu îi vorbesc"
        )
        verdict = (
            f"Oferta nu e problema: {who} lui «{avatar.name}», deci CPA-ul mare vine din mesaj, "
            "nu din ofertă. Întâi rescrierea, apoi judecăm oferta."
        )
    elif gap is not None:
        status = "positioning_gap"
        focus = gap.name
        verdict = (
            f"Oferta se poate poziționa mai bine: «{gap.name}» cumpără mai ușor decât caută "
            f"({_shares(gap)}), dar mesajul e construit pentru «{avatar.name}» ({_shares(own)})."
        )
    else:
        status = "fit"
        focus = avatar.name
        if unprofitable:
            verdict = (
                f"Oferta nu e cauza pierderilor: nicio reclamă care îi vorbește lui "
                f"«{avatar.name}» nu pierde bani. Banii se pierd în altă parte (vezi CFO-ul)."
            )
        elif own.buyer_share is not None:
            verdict = (
                f"Oferta se potrivește cu piața: «{avatar.name}» e și cel care cumpără "
                f"({_shares(own)})."
            )
        else:
            verdict = (
                "Oferta nu dă semne de nepotrivire, dar potrivirea cu piața se dovedește abia "
                "după primele conversii."
            )
    if gap is not None and status != "pivot":
        moves.append(
            _move(
                "reposition",
                f"repoziționarea ofertei pe «{gap.name}» ({_BY_KEY[gap.key].voice})",
                _reach(gap),
                confidence,
            )
        )
    if misaligned:
        moves.append(
            _move(
                "message",
                f"rescrierea mesajului pentru «{avatar.name}» ({_BY_KEY[avatar.key].voice})",
                _reach(own),
                confidence,
            )
        )
    moves += choice_moves
    if scorer is not None and moves:
        moves = _scored_by_jev(moves, scorer)
    moves.sort(key=lambda move: -move.rice)

    archetype = _BY_KEY[target.key]
    positioning = (
        f"Pentru «{target.name}», care vrea {archetype.desires[0]}, oferta e despre {about}; "
        f"dovada care îl convinge: {archetype.proof_points[0]}."
    )
    rivals = list(
        dict.fromkeys(
            finding.source
            for finding in (market.web_findings if market is not None else [])
            if finding.query.startswith("competitori")
        )
    )
    if rivals:
        positioning += (
            f" Alternativele pe care le compară (găsite pe web): {', '.join(rivals[:3])}."
        )
    # Povestea, cu cuvintele clientului cand le avem (JTBD): situatia si progresul dorit.
    jtbd = directive.customer_avatar
    problem = archetype.pains[0]
    promise = archetype.desires[0]
    if jtbd is not None and target is own:
        problem = f"«{jtbd.customer_situation}»" if jtbd.customer_situation else problem
        promise = f"«{jtbd.desired_progress}»" if jtbd.desired_progress else promise
    if status == "pivot" and pain is not None:
        problem = f"piața caută acum «{pain.theme}»"
    story = f"Problema: {problem}. Promisiunea: {promise}. Dovada: {archetype.proof_points[0]}."
    summary = f"{verdict} Poziționarea: {positioning} Povestea ofertei: {story}"
    if choice:
        summary += f" {choice}"
    if moves:
        summary += f" Prioritatea (RICE): {moves[0].text} (scor {moves[0].rice})."
    return ProductDirective(
        client_account_id=directive.client_account_id,
        status=status,
        cpa_alarm=unprofitable,
        verdict=verdict,
        focus=focus,
        best_fit=gap.name if gap is not None else None,
        positioning=positioning,
        story=story,
        moves=moves,
        summary=summary,
        generated_at=generated_at,
        choice_architecture=choice,
    )


def cpo_facts(product: ProductDirective) -> str:
    """Faptele CPO-ului - singura lui sursa de adevar."""
    lines = [f"Verdictul pe ofertă (calculat determinist, obligatoriu): {product.verdict}"]
    if product.positioning:
        lines.append(f"Poziționarea (clientul care cumpără cel mai ușor): {product.positioning}")
    if product.story:
        lines.append(f"Povestea ofertei (problemă, promisiune, dovadă): {product.story}")
    if product.choice_architecture:
        lines.append(product.choice_architecture)
    lines.extend(
        f"Mutarea {index} după RICE: {move.text}. Reach {move.reach}% din cerere, impact "
        f"{_number(move.impact)}, încredere {_percent(move.confidence)}, efort "
        f"{_number(move.effort)} săptămâni: scor {move.rice}."
        for index, move in enumerate(product.moves, start=1)
    )
    return "\n".join(f"- {line}" for line in lines)
