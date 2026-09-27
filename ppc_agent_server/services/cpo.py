"""CPO-ul (Chief Product Officer): apara oferta si potrivirea ei cu piata.

Al cincilea membru al consiliului Reginei (``council.py``). Ceilalti judeca
mesajul (Regina), banii (CFO-ul), infrastructura (Tehnicianul) si piata
(Researcher-ul); CPO-ul judeca OFERTA - ce vinde clientul si cui. Cand CFO-ul
gaseste contul nerentabil, desparte doua cauze care arata la fel in cifre:

- **mesajul**: reclamele nu ii vorbesc clientului ideal -> oferta ramane, se
  rescrie mesajul (CPO-ul o apara);
- **oferta**: reclamele ii vorbesc deja clientului ideal si tot pierd bani ->
  oferta nu convinge. Pivotarea se propune doar spre un semnal real: durerea care
  creste in piata (Researcher-ul, niciodata din date demonstrative) sau segmentul
  care cumpara mai usor decat cauta. Fara semnal, oferta se testeaza, nu se schimba.

Framework-uri de produs (idei din menkesu/awesome-pm-skills, niciun rand copiat):

- **Positioning** (April Dunford): pornesti de la clientii care cumpara cel mai
  usor, nu de la cei care cauta cel mai mult. Indicele de potrivire al unui
  segment = cota lui din conversii / cota din cautari; de la 1,25, cu cel putin
  20% din conversii, segmentul e "best-fit". Daca nu e clientul ideal caruia ii
  vorbesc reclamele, pozitionarea se poate ascuti.
- **Strategic storytelling**: povestea ofertei in trei timpi - problema (durerea
  profilului), promisiunea (dorinta lui), dovada (ce il convinge).
- **RICE** (Intercom): mutarile de oferta, ordonate dupa Reach x Impact x
  Confidence / Effort. Reach = procentul din conversii atins (din cautari, cat timp
  conversiile nu ajung), Impact pe scara 0,5-3, Confidence din cat de solide sunt
  datele, Effort in saptamani.

Modul pur si determinist: fara DB, fara LLM. Vocea (``council.py``) doar formuleaza.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ppc_agent_server.services.humanizer import CONSULTANT_VOICE
from ppc_agent_server.services.memory import HISTORY_RULE
from ppc_agent_server.services.queen_agent import (
    _BY_KEY,
    AdAlignment,
    AvatarSegment,
    BrandStrategyDirective,
    _quote,
)
from ppc_agent_server.services.researcher import MarketDirective, PainSignal
from ppc_agent_server.services.ro_format import percent as _percent
from ppc_agent_server.services.ro_format import ron as _ron

OfferStatus = Literal["fit", "message_gap", "positioning_gap", "offer_gap", "pivot", "unknown"]
MoveKind = Literal["pivot", "reposition", "offer_test", "message"]

#: Un segment e "best-fit" cand cumpara de atatea ori mai usor decat cauta...
FIT_INDEX_MIN = 1.25
#: ...si aduce cel putin atat din conversii (sub, e zgomot).
FIT_MIN_BUYERS = 0.2
#: Impactul (RICE: 3 masiv, 2 mare, 1 mediu, 0,5 mic) si efortul (saptamani), pe mutare.
# ponytail: estimari fixe pe tip de mutare; calibreaza-le din rezultatele propunerilor aplicate.
_RICE: dict[MoveKind, tuple[float, float]] = {
    "pivot": (3.0, 4.0),
    "reposition": (2.0, 2.0),
    "offer_test": (2.0, 1.0),
    "message": (1.0, 0.5),
}


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
        rice=round(points * impact * confidence / effort),
    )


def evaluate_offer(
    directive: BrandStrategyDirective,
    *,
    unprofitable: bool,
    market: MarketDirective | None = None,
    generated_at: datetime,
) -> ProductDirective:
    """Verdictul CPO-ului pe oferta.

    ``unprofitable`` = CFO-ul a gasit contul nerentabil pe cifre de incredere (cu
    tracking-ul picat, cifrele nu declanseaza nicio pivotare). Piata intra doar
    din surse reale; concurentii gasiti pe web intra doar in pozitionare.
    """
    avatar = directive.avatar
    if directive.status != "ok" or avatar is None:
        unknown = (
            "Oferta nu se poate judeca încă: lipsește clientul ideal (prea puține căutări "
            "atribuite)."
        )
        return ProductDirective(
            client_account_id=directive.client_account_id,
            status="unknown",
            cpa_alarm=unprofitable,
            verdict=unknown,
            focus=None,
            best_fit=None,
            positioning="",
            story="",
            moves=[],
            summary=unknown,
            generated_at=generated_at,
        )

    own = next(segment for segment in directive.segments if segment.key == avatar.key)
    confidence = 0.8 if own.buyer_share is not None else 0.5
    best = best_fit_segment(directive)
    gap = best if best is not None and best.key != avatar.key else None
    pain: PainSignal | None = None
    if market is not None and not market.is_demo and market.social_sentiment.rising:
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
    problem = archetype.pains[0]
    if status == "pivot" and pain is not None:
        problem = f"piața caută acum «{pain.theme}»"
    story = (
        f"Problema: {problem}. Promisiunea: {archetype.desires[0]}. "
        f"Dovada: {archetype.proof_points[0]}."
    )
    summary = f"{verdict} Poziționarea: {positioning} Povestea ofertei: {story}"
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
    )


def cpo_facts(product: ProductDirective) -> str:
    """Faptele CPO-ului - singura lui sursa de adevar."""
    lines = [f"Verdictul pe ofertă (calculat determinist, obligatoriu): {product.verdict}"]
    if product.positioning:
        lines.append(f"Poziționarea (clientul care cumpără cel mai ușor): {product.positioning}")
    if product.story:
        lines.append(f"Povestea ofertei (problemă, promisiune, dovadă): {product.story}")
    lines.extend(
        f"Mutarea {index} după RICE: {move.text}. Reach {move.reach}% din cerere, impact "
        f"{_number(move.impact)}, încredere {_percent(move.confidence)}, efort "
        f"{_number(move.effort)} săptămâni: scor {move.rice}."
        for index, move in enumerate(product.moves, start=1)
    )
    return "\n".join(f"- {line}" for line in lines)


CPO_SYSTEM_PROMPT = (
    "Ești CPO-ul (Chief Product Officer) din consiliul agenției AC Media: aperi OFERTA clientului "
    "și potrivirea ei cu piața. Primești întrebarea clientului (proprietarul afacerii) și FAPTELE "
    "DE PRODUS: verdictul pe ofertă, poziționarea (clientul care cumpără cel mai ușor), povestea "
    "ofertei și mutările ordonate după RICE.\n"
    "Reguli stricte:\n"
    "1. Judeci DOAR oferta: ce vinde clientul și cui. Mesajul reclamelor e al Reginei, banii ai "
    "CFO-ului, piața a Researcher-ului: le folosești concluziile, nu le refaci.\n"
    "2. Verdictul pe ofertă din FAPTE e obligatoriu. Când CPA-ul e mare, spui clar dacă vina e a "
    "mesajului sau a ofertei; o pivotare e o propunere, nu o decizie luată.\n"
    "3. Folosești DOAR FAPTELE. Nicio cifră care nu apare în ele.\n"
    "4. Nu pretinzi că ai făcut ceva și nu promiți rezultate.\n"
    "5. Maximum 80 de cuvinte, text simplu, fără markdown, liste sau linkuri.\n"
    f"6. {HISTORY_RULE}\n\n"
    f"{CONSULTANT_VOICE}"
)
