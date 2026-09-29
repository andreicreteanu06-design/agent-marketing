"""Traficul din GA4 si pozitiile organice, pentru Regina (CMO).

Regina judeca brandul din cautari si reclame; fara trafic, o scadere din Meta Ads
arata ca o pierdere de clienti chiar si cand cererea s-a mutat doar pe Google
organic. Aici se aduna, pe doua perioade egale (ultimele 28 de zile si cele 28
dinainte):

- **sesiunile pe canal din GA4** (``sessionDefaultChannelGroup``): *Paid Social*
  (Meta) si *Organic Search* (Google), plus *Paid Search* cand exista;
- **Google organic din Search Console**: click-uri, afisari, pozitia medie;
- **pozitiile urmarite in SERP** (``SerpPosition``, OpenSERP): cuvintele care au
  urcat sau au coborat cel mai mult.

Corelarea e determinista (:func:`build_organic_context`): Meta scade cu cel putin
10% iar organicul creste cu cel putin 10% -> ``organic_offsets_paid``; scad amandoua
-> ``both_declining``; scade doar Meta -> ``paid_decline_only``. Sub
:data:`MIN_CHANNEL_SESSIONS` pe un canal, schimbarea e zgomot si nu se judeca. E o
corelare, nu o cauza: textul spune "pare", nu "a mutat".

Modulul e pur: fara DB, fara HTTP. Datele vin din ``queen_signals.py`` - doar din
conturi conectate (``live``), niciodata din datele demonstrative ale paginii "Trafic &
Pozitii".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from ppc_agent_server.services.ro_format import count as _count
from ppc_agent_server.services.ro_format import decimal as _decimal
from ppc_agent_server.services.ro_format import percent as _percent

OrganicShift = Literal[
    "organic_offsets_paid",
    "both_declining",
    "paid_decline_only",
    "organic_growth",
    "stable",
    "unknown",
]

#: Canalele GA4 (``sessionDefaultChannelGroup``) pe care le compara Regina.
PAID_SOCIAL = "Paid Social"
ORGANIC_SEARCH = "Organic Search"
PAID_SEARCH = "Paid Search"
_CHANNEL_NAMES = {
    PAID_SOCIAL: "Paid Social (Meta)",
    ORGANIC_SEARCH: "Organic Search (Google)",
    PAID_SEARCH: "Paid Search (Google Ads)",
}
#: De la +/-10% un canal "se misca".
CHANNEL_CHANGE_MIN = 0.10
#: Sub atatea sesiuni in cele doua perioade la un loc, schimbarea unui canal e zgomot.
MIN_CHANNEL_SESSIONS = 50
#: O pozitie urmarita "s-a miscat" de la atatea locuri.
RANK_MOVE_MIN = 2.0
#: Cate cuvinte urmarite ajung in fapte - cele mai mari miscari primele.
MAX_KEYWORD_MOVES = 3


@dataclass(frozen=True, slots=True)
class ChannelSessions:
    """Sesiunile unui canal GA4 in perioada curenta si in cea de dinainte."""

    channel: str
    sessions_now: int
    sessions_before: int


@dataclass(frozen=True, slots=True)
class OrganicSearchTotals:
    """Google organic din Search Console, pe cele doua perioade."""

    clicks_now: int
    clicks_before: int
    impressions_now: int
    impressions_before: int
    #: Pozitia medie ponderata cu afisarile; ``None`` = nicio afisare.
    position_now: float | None
    position_before: float | None


@dataclass(frozen=True, slots=True)
class KeywordRank:
    """Un cuvant urmarit in SERP: locul la ultima verificare din fiecare perioada."""

    keyword: str
    #: ``None`` = verificat, dar nu apare in rezultatele citite.
    rank_before: float | None
    rank_now: float | None


@dataclass(frozen=True, slots=True)
class OrganicSignals:
    """Tot ce stie Regina despre trafic: GA4, Search Console, pozitiile urmarite."""

    window_days: int
    channels: Sequence[ChannelSessions] = ()
    search: OrganicSearchTotals | None = None
    keywords: Sequence[KeywordRank] = ()
    #: Ce lipseste si de ce (GA4 neconectat, Search Console fara raspuns).
    notes: Sequence[str] = ()


class OrganicContext(BaseModel):
    """Corelarea Meta - organic, calculata determinist, cu dovezile ei."""

    window_days: int
    shift: OrganicShift
    #: Schimbarea sesiunilor (acum fata de inainte); ``None`` = canal absent sau prea mic.
    paid_social_change: float | None
    organic_search_change: float | None
    #: Cifrele, rand cu rand (GA4, Search Console, pozitiile urmarite).
    evidence: list[str]
    #: Ce inseamna pentru client, intr-o fraza; gol fara date.
    implication: str
    notes: list[str]


def _change(now: float, before: float) -> float | None:
    return (now - before) / before if before > 0 else None


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}{_percent(abs(value))}"


def _channel_change(channel: ChannelSessions | None) -> float | None:
    if channel is None or channel.sessions_now + channel.sessions_before < MIN_CHANNEL_SESSIONS:
        return None
    return _change(channel.sessions_now, channel.sessions_before)


def _shift(paid: float | None, organic: float | None) -> OrganicShift:
    if paid is None or organic is None:
        return "unknown"
    if paid <= -CHANNEL_CHANGE_MIN:
        if organic >= CHANNEL_CHANGE_MIN:
            return "organic_offsets_paid"
        if organic <= -CHANNEL_CHANGE_MIN:
            return "both_declining"
        return "paid_decline_only"
    if organic >= CHANNEL_CHANGE_MIN:
        return "organic_growth"
    return "stable"


def _channel_line(channel: ChannelSessions) -> str:
    name = _CHANNEL_NAMES.get(channel.channel, channel.channel)
    change = _change(channel.sessions_now, channel.sessions_before)
    text = f"{name} {_count(channel.sessions_now, 'sesiuni', 'sesiune')}"
    if change is not None:
        text += f" ({_signed(change)})"
    return text


def _search_line(search: OrganicSearchTotals) -> str:
    text = f"Google organic (Search Console): {_count(search.clicks_now, 'click-uri', 'click')}"
    change = _change(search.clicks_now, search.clicks_before)
    if change is not None:
        text += f" ({_signed(change)})"
    text += f", {_count(search.impressions_now, 'afișări', 'afișare')}"
    if search.position_now is not None:
        text += f", poziție medie {_decimal(search.position_now)}"
        if search.position_before is not None:
            text += f" (înainte {_decimal(search.position_before)})"
    return text + "."


def _rank(value: float | None) -> str:
    return f"locul {_decimal(value, 0)}" if value is not None else "în afara rezultatelor"


def _keyword_moves(keywords: Sequence[KeywordRank]) -> list[str]:
    def _moved(keyword: KeywordRank) -> float:
        # "In afara rezultatelor" conteaza ca locul 101: intrarea in top e o miscare mare.
        before = keyword.rank_before if keyword.rank_before is not None else 101.0
        now = keyword.rank_now if keyword.rank_now is not None else 101.0
        return before - now

    moved = [keyword for keyword in keywords if abs(_moved(keyword)) >= RANK_MOVE_MIN]
    moved.sort(key=lambda keyword: (-abs(_moved(keyword)), keyword.keyword))
    return [
        f"«{keyword.keyword}»: {_rank(keyword.rank_before)} -> {_rank(keyword.rank_now)}"
        for keyword in moved[:MAX_KEYWORD_MOVES]
    ]


_IMPLICATIONS: dict[OrganicShift, str] = {
    "organic_offsets_paid": (
        "Meta aduce mai puțin trafic, dar Google organic a crescut în aceeași perioadă: o parte "
        "din cerere pare să vină acum pe organic. Scăderea din Meta nu înseamnă automat clienți "
        "pierduți."
    ),
    "both_declining": (
        "Scad și Meta, și Google organic: cererea sau sezonul trag în jos, nu doar reclamele."
    ),
    "paid_decline_only": (
        "Scade doar traficul din Meta, organicul e stabil: cauza e în campanii (creative, public, "
        "livrare), nu în piață."
    ),
    "organic_growth": (
        "Google organic crește fără ca Meta să scadă: încă un canal care aduce vizitatori."
    ),
    "stable": "Traficul din Meta și cel din Google organic sunt stabile.",
    "unknown": "",
}


def build_organic_context(signals: OrganicSignals) -> OrganicContext:
    """Corelarea Meta - organic din semnale - functie pura, determinista."""
    by_channel = {channel.channel: channel for channel in signals.channels}
    paid = _channel_change(by_channel.get(PAID_SOCIAL))
    organic = _channel_change(by_channel.get(ORGANIC_SEARCH))
    shift = _shift(paid, organic)
    evidence: list[str] = []
    shown = [by_channel[name] for name in (PAID_SOCIAL, ORGANIC_SEARCH, PAID_SEARCH)
             if name in by_channel]
    if shown:
        evidence.append(
            f"GA4, ultimele {_count(signals.window_days, 'zile')} față de cele "
            f"{signals.window_days} dinainte: {'; '.join(_channel_line(c) for c in shown)}."
        )
    if signals.search is not None:
        evidence.append(_search_line(signals.search))
    moves = _keyword_moves(signals.keywords)
    if moves:
        evidence.append(f"Poziții urmărite în Google: {'; '.join(moves)}.")
    notes = list(signals.notes)
    if signals.channels and shift == "unknown":
        notes.append(
            f"Prea puțin trafic pe Meta sau pe Google organic în GA4 (sub "
            f"{MIN_CHANNEL_SESSIONS} de sesiuni) ca schimbarea să însemne ceva."
        )
    return OrganicContext(
        window_days=signals.window_days,
        shift=shift,
        paid_social_change=round(paid, 4) if paid is not None else None,
        organic_search_change=round(organic, 4) if organic is not None else None,
        evidence=evidence,
        implication=_IMPLICATIONS[shift],
        notes=notes,
    )


def organic_facts(context: OrganicContext) -> list[str]:
    """Randurile de fapte pentru Regina: cifrele, apoi corelarea (obligatorie)."""
    lines = [f"Trafic (calculat determinist): {line}" for line in context.evidence]
    if context.implication:
        lines.append(f"Meta față de organic (obligatoriu): {context.implication}")
    lines.extend(context.notes)
    return lines
