"""Interviul din chat inaintea primei campanii: costurile clientului si zona reclamelor.

Consiliul nu lanseaza nimic pana nu stie cat castiga clientul dintr-o vanzare (de acolo
CAC-ul maxim si pragul de rentabilitate - ``ppc_agent.client_economics``) si unde sunt
clientii lui. Intrebarile vin pe rand, in chat; fiecare raspuns se salveaza imediat, deci
interviul se poate relua oricand de unde a ramas.

Cand porneste: la prima propunere de lansare fara costuri (``routers/campaigns.py``) sau
cand clientul vorbeste in chat despre o campanie. Cat timp o intrebare asteapta raspuns,
mesajele din chat sunt raspunsuri - nu ajung la consiliu (si nu consuma modelele).
"anuleaza" il opreste; "actualizeaza costurile" / "schimba zona" il repornesc; "raza 8 km"
schimba raza aleasa.

Raspunsurile se inteleg fara model: numere romanesti ("1.250,50 lei", "40%", "3 din 10"),
cifra unei variante sau cuvinte cheie. Ce nu se intelege primeste intrebarea din nou, cu
un exemplu - nimic nu se ghiceste.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from sqlmodel import Session

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.client_economics import (
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
    BusinessKind,
    EconomicsError,
    PlaceSize,
    Thresholds,
    choose_radius,
    lead_thresholds,
    shop_thresholds,
)
from ppc_agent.errors import PpcAgentError
from ppc_agent_server.models import ClientAccount
from ppc_agent_server.services.geocoding import Geocoder

_HUNDRED = Decimal("100")

#: Mesajele care pornesc interviul, cand costurile lipsesc (fara diacritice): intentia de
#: a lansa, nu orice intrebare despre buget - "merita sa cresc bugetul?" e pentru consiliu.
_LAUNCH_WORDS = (
    "lans",
    "prima campanie",
    "campanie noua",
    "o campanie",
    "incepem",
    "pornim",
    "vreau reclame",
    "costuri",
    "costurile",
)
_CANCEL = frozenset({"anuleaza", "mai tarziu", "renunt", "stop", "lasa", "nu acum"})
_RESTART_COSTS = frozenset(
    {"actualizeaza costurile", "schimba costurile", "costurile mele", "refa costurile"}
)
_RESTART_AREA = frozenset({"schimba zona", "schimba adresa", "alta adresa", "refa zona"})
_RADIUS_COMMAND = re.compile(r"^raza(?: de)? (\d+(?:[.,]\d+)?) ?(?:km|kilometri)?$")

_COST_FIELDS = (
    "average_order_value",
    "product_cost",
    "shipping_cost",
    "payment_fee_pct",
    "return_rate_pct",
    "customer_profit",
    "close_rate_pct",
)
_AREA_FIELDS = (
    "service_area",
    "business_address",
    "business_kind",
    "location_label",
    "place_size",
)


def plain(text: str) -> str:
    """Litere mici, fara diacritice, punctuatie si spatii in plus."""
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(char)
    )
    return " ".join(re.sub(r"[^a-z0-9%.,/ ]", " ", stripped).split())


# --- numerele din raspunsuri ----------------------------------------------------------

_NUMBER = re.compile(r"\d[\d.,]*")
_ZERO_WORDS = ("zero", "nimic", "nu am", "niciun", "nicio", "gratuit", "il plateste clientul")


def parse_number(text: str) -> Decimal | None:
    """Primul numar din ``text``, in scrierea romaneasca sau engleza.

    ``1.250,50`` si ``1,250.50`` -> 1250.50; ``2,5`` -> 2.5; ``1.250`` -> 1250 (grupe de
    trei cifre = mii); ``150.5`` -> 150.5.
    """
    match = _NUMBER.search(text)
    if match is None:
        return None
    token = match.group().rstrip(".,")
    if "." in token and "," in token:
        decimal_mark = "." if token.rfind(".") > token.rfind(",") else ","
        thousands = "," if decimal_mark == "." else "."
        token = token.replace(thousands, "").replace(decimal_mark, ".")
    elif "," in token:
        # "2,5" e o zecimala; mai multe virgule ("1,250,000") sunt grupe de mii.
        token = token.replace(",", "") if token.count(",") > 1 else token.replace(",", ".")
    elif "." in token:
        # "1.250" sau "1.250.000": grupe de trei cifre = mii; "150.5" e o zecimala.
        if token.count(".") > 1 or len(token.rpartition(".")[2]) == 3:
            token = token.replace(".", "")
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Decimal | None:
    """O suma in lei; ``0`` pentru "nimic", "nu am", "il plateste clientul"."""
    value = parse_number(text)
    if value is None and any(word in text for word in _ZERO_WORDS):
        return Decimal("0")
    return value


def parse_share(text: str, *, out_of: int) -> Decimal | None:
    """Un procent: "40%", "3 din 10", sau un numar simplu raportat la ``out_of``."""
    ratio = re.search(r"(\d+(?:[.,]\d+)?) ?din ?(\d+)", text)
    if ratio:
        part = parse_number(ratio.group(1))
        whole = parse_number(ratio.group(2))
        if part is not None and whole:
            return (part / whole * _HUNDRED).quantize(Decimal("0.01"))
    value = parse_amount(text)
    if value is None:
        return None
    if "%" in text or "la suta" in text or "procent" in text or out_of == 100:
        return value
    return (value / out_of * _HUNDRED).quantize(Decimal("0.01"))


# --- intrebarile ----------------------------------------------------------------------

_KIND_CHOICES: dict[str, BusinessKind] = {
    "1": "zilnic",
    "2": "programat",
    "3": "destinatie",
    "4": "livrare",
}
_KIND_WORDS: tuple[tuple[BusinessKind, tuple[str, ...]], ...] = (
    ("livrare", ("livr", "deplasez", "domiciliu", "merg la client", "vin la client")),
    ("destinatie", ("mobil", "nunt", "eveniment", "construct", "imobil", "renov", "bijuter")),
    (
        "programat",
        (
            "service",
            "cabinet",
            "clinic",
            "dentist",
            "stomat",
            "avocat",
            "programar",
            "medic",
            "curs",
        ),
    ),
    (
        "zilnic",
        (
            "cafe",
            "salon",
            "frizer",
            "coafur",
            "restaurant",
            "sala",
            "fitness",
            "bar",
            "patiser",
            "brutar",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    question: str
    #: De ce intreaba consiliul - raspunsul la "de ce?" sau la o intrebare a clientului.
    why: str
    #: Un exemplu de raspuns, pentru cand n-am inteles.
    example: str


_STEPS: dict[str, Step] = {
    "average_order_value": Step(
        "average_order_value",
        "Care e valoarea medie a unei comenzi, în lei, cu TVA?",
        "Din ea și din costuri calculez cât poți plăti în reclame pentru o vânzare.",
        "«250 lei»",
    ),
    "product_cost": Step(
        "product_cost",
        "Cât te costă, în medie, produsele dintr-o comandă (achiziție sau producție)?",
        "Fără costul produsului, o vânzare ar părea profit întreg.",
        "«110 lei» sau «0» dacă vinzi un serviciu",
    ),
    "shipping_cost": Step(
        "shipping_cost",
        "Cât plătești tu transportul și ambalajul pentru o comandă?",
        "Transportul plătit de tine scade profitul fiecărei comenzi.",
        "«18 lei», sau «îl plătește clientul»",
    ),
    "payment_fee_pct": Step(
        "payment_fee_pct",
        "Ce comision plătești la încasare (procesatorul de plăți, rambursul), în procente?",
        "Comisionul se ia din fiecare comandă.",
        "«2%», sau «0» dacă nu plătești",
    ),
    "return_rate_pct": Step(
        "return_rate_pct",
        "Din 100 de comenzi, câte sunt returnate sau refuzate la livrare?",
        "O comandă returnată nu aduce bani, dar reclama ei a costat.",
        "«5», sau «nimic»",
    ),
    "customer_profit": Step(
        "customer_profit",
        "Cât câștigi, după costurile tale, dintr-un client nou (profit, nu încasare)?",
        "Atât poți plăti, cel mult, ca să câștigi un client fără să pierzi bani.",
        "«600 lei»",
    ),
    "close_rate_pct": Step(
        "close_rate_pct",
        "Din 10 cereri primite (formulare, apeluri), câte devin clienți?",
        "Din ea iese cât valorează o cerere, deci cât poți plăti pe una.",
        "«3 din 10» sau «30%»",
    ),
    "service_area": Step(
        "service_area",
        "Unde sunt clienții tăi? 1) local - vin la tine sau mergi tu la ei, într-o zonă; "
        "2) în toată țara - vinzi online sau livrezi peste tot.",
        "O afacere locală nu are ce face cu reclame în toată țara: banii ar ajunge la oameni "
        "care nu vin niciodată.",
        "«1» sau «2»",
    ),
    "business_address": Step(
        "business_address",
        "Care e adresa exactă a afacerii (stradă, număr, oraș)?",
        "Reclamele locale merg pe o rază în jurul ei.",
        "«Str. Memorandumului 28, Cluj-Napoca»",
    ),
    "business_kind": Step(
        "business_kind",
        "Ce fel de afacere e? 1) vin des și din apropiere (cafenea, salon, frizerie, sală); "
        "2) cu programare (service auto, cabinet, clinică); 3) o achiziție mare pentru care "
        "oamenii fac drum (mobilă, nunți, construcții); 4) livrezi sau mergi tu la client.",
        "De el depinde cât de departe vin oamenii: la o cafenea, din cartier; pentru o "
        "mobilă, din tot județul.",
        "«2», sau «service auto»",
    ),
    "max_travel_km": Step(
        "max_travel_km",
        "Până unde vrei să ajungă reclamele? Spune-mi în kilometri, «tot orașul», «tot "
        "județul», sau «nu știu» și aleg eu.",
        "Raza o aleg din tipul afacerii și mărimea localității; a ta e limita de sus.",
        "«10 km» sau «nu știu»",
    ),
}

_INTRO = (
    "Înainte de prima campanie, consiliul are nevoie de câteva cifre: din ele calculez cât "
    "poți plăti în reclame pentru un client fără să pierzi bani, și unde merg reclamele. "
    "Durează un minut; «anulează» oprește, iar răspunsurile date rămân salvate."
)


def _missing(account: ClientAccount) -> str | None:
    """Prima intrebare fara raspuns, in ordine; ``None`` cand totul e completat."""
    cost_steps = (
        (
            "average_order_value",
            "product_cost",
            "shipping_cost",
            "payment_fee_pct",
            "return_rate_pct",
        )
        if account.objective is CampaignObjective.SALES
        else ("customer_profit", "close_rate_pct")
    )
    for key in cost_steps:
        if getattr(account, key) is None:
            return key
    if account.service_area not in ("local", "national"):
        return "service_area"
    if account.service_area == "national":
        return None
    if account.location_lat is None:
        return "business_address"
    if not account.business_kind:
        return "business_kind"
    if account.target_radius_km is None:
        return "max_travel_km"
    return None


def first_question(account: ClientAccount) -> str | None:
    """Intrebarea la care trebuie sa raspunda clientul acum (``None`` = nimic lipsa)."""
    step = _missing(account)
    return _STEPS[step].question if step else None


def thresholds(account: ClientAccount) -> Thresholds | None:
    """Pragurile din costurile salvate; ``None`` cat timp lipsesc."""
    try:
        if account.objective is CampaignObjective.SALES:
            if None in (
                account.average_order_value,
                account.product_cost,
                account.shipping_cost,
                account.payment_fee_pct,
                account.return_rate_pct,
            ):
                return None
            return shop_thresholds(
                average_order_value=account.average_order_value or Decimal("0"),
                product_cost=account.product_cost or Decimal("0"),
                shipping_cost=account.shipping_cost or Decimal("0"),
                payment_fee_pct=account.payment_fee_pct or Decimal("0"),
                return_rate_pct=account.return_rate_pct or Decimal("0"),
            )
        if account.customer_profit is None or account.close_rate_pct is None:
            return None
        return lead_thresholds(
            customer_profit=account.customer_profit, close_rate_pct=account.close_rate_pct
        )
    except EconomicsError:
        return None


def _ron(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return text.removesuffix(",00")


def summary(account: ClientAccount, limits: Thresholds) -> str:
    """Ce a inteles consiliul: pragurile de profit si zona reclamelor."""
    if account.objective is CampaignObjective.SALES:
        money = (
            f"Dintr-o comandă de {_ron(account.average_order_value or Decimal('0'))} lei îți "
            f"rămân {_ron(limits.max_cac)} lei înainte de reclame (marjă "
            f"{_ron(limits.margin_pct)}%). Deci CAC-ul maxim e {_ron(limits.max_cac)} lei - cât "
            "poți plăti în reclame pentru o comandă fără să pierzi - iar ROAS-ul minim e "
            f"{_ron(limits.break_even_roas)}: sub el, campania pierde bani."
        )
    else:
        money = (
            f"Un client nou îți aduce {_ron(limits.max_cac)} lei profit, iar "
            f"{_ron(account.close_rate_pct or Decimal('0'))}% din cereri devin clienți. Deci o "
            f"cerere valorează {_ron(limits.conversion_value)} lei: atât poți plăti, cel mult, "
            f"pe un lead (CPL maxim), și {_ron(limits.max_cac)} lei pe un client (CAC maxim)."
        )
    if account.service_area == "national":
        area = "Reclamele merg în toată țara."
    else:
        area = (
            f"Reclamele merg pe o rază de {_ron(account.target_radius_km or Decimal('0'))} km în "
            f"jurul adresei {account.location_label or account.business_address}. Altă rază: "
            "scrie «raza 8 km»."
        )
    return f"{money} {area}"


def _finish(account: ClientAccount, now: datetime) -> str:
    limits = thresholds(account)
    if limits is None:  # costurile nu lasa profit: le reluam
        raise EconomicsError("costurile nu lasă loc de profit")
    if account.objective is CampaignObjective.SALES:
        account.min_roas = limits.break_even_roas
    account.default_lead_value = limits.conversion_value
    account.economics_confirmed_at = now
    account.intake_step = ""
    return (
        "Gata, am tot ce-mi trebuie. "
        + summary(account, limits)
        + " Consiliul judecă de acum fiecare campanie după aceste praguri; poți propune "
        "prima campanie."
    )


def _apply(account: ClientAccount, key: str, text: str, geocoder: Geocoder) -> str | None:
    """Salveaza raspunsul la ``key``. Intoarce un mesaj de eroare cand nu l-am inteles."""
    if key in ("average_order_value", "product_cost", "shipping_cost", "customer_profit"):
        amount = parse_amount(text)
        if (
            amount is None
            or amount < 0
            or (key in ("average_order_value", "customer_profit") and amount == 0)
        ):
            return None
        setattr(account, key, amount.quantize(Decimal("0.01")))
        return ""
    if key in ("payment_fee_pct", "return_rate_pct", "close_rate_pct"):
        share = parse_share(text, out_of=10 if key == "close_rate_pct" else 100)
        if (
            share is None
            or not (Decimal("0") <= share < _HUNDRED)
            or (key == "close_rate_pct" and share == 0)
        ):
            return None
        setattr(account, key, share)
        return ""
    if key == "service_area":
        if text.startswith("1") or any(
            word in text for word in ("local", "zona", "vin la", "oras", "cartier")
        ):
            account.service_area = "local"
        elif text.startswith("2") or any(
            word in text for word in ("tara", "national", "online", "curier", "peste tot")
        ):
            account.service_area = "national"
        else:
            return None
        return ""
    if key == "business_address":
        try:
            place = geocoder(text, account.geo or "RO")
        except PpcAgentError:
            return "Nu pot verifica adresa pe hartă acum. Mai încearcă o dată peste câteva minute."
        if place is None:
            return (
                "Nu am găsit adresa pe hartă. Scrie strada, numărul și orașul, ca pe un plic - "
                "de exemplu «Str. Memorandumului 28, Cluj-Napoca»."
            )
        account.business_address = text[:300]
        account.location_lat = place.latitude
        account.location_lng = place.longitude
        account.location_label = place.label
        account.place_size = place.size
        return ""
    if key == "business_kind":
        kind = _KIND_CHOICES.get(text[:1]) or next(
            (choice for choice, words in _KIND_WORDS if any(word in text for word in words)), None
        )
        if kind is None:
            return None
        account.business_kind = kind
        return ""
    if key == "max_travel_km":
        size = _size(account)
        if "judet" in text:
            limit: Decimal | None = Decimal("50")
        elif "oras" in text:
            limit = {
                "oras_mare": Decimal("15"),
                "oras": Decimal("8"),
                "localitate_mica": Decimal("5"),
            }[size]
        elif any(
            word in text for word in ("nu stiu", "decide", "alege", "tu ", "oricat")
        ) or text in ("tu", "nu"):
            limit = None
        else:
            limit = parse_number(text)
            if limit is None or limit <= 0:
                return None
        choice = choose_radius(_kind(account), size, limit)
        account.max_travel_km = limit
        account.target_radius_km = choice.radius_km
        return choice.reason
    return None


def handle_message(
    session: Session,
    account: ClientAccount,
    message: str,
    *,
    geocoder: Geocoder,
    now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> str | None:
    """Raspunsul interviului la ``message``, sau ``None`` cand mesajul e pentru consiliu."""
    text = plain(message)
    radius = _RADIUS_COMMAND.match(text)
    if radius:
        if account.service_area != "local" or account.location_lat is None:
            return (
                "Raza se schimbă doar când reclamele merg în jurul adresei afacerii. Scrie "
                "«schimbă zona» ca să stabilim zona."
            )
        wanted = parse_number(radius.group(1)) or MIN_RADIUS_KM
        account.target_radius_km = min(MAX_RADIUS_KM, max(MIN_RADIUS_KM, wanted))
        account.max_travel_km = account.target_radius_km
        _save(session, account)
        return (
            f"Am schimbat raza la {_ron(account.target_radius_km)} km în jurul adresei "
            f"{account.location_label or account.business_address}. Se aplică la următoarea "
            "campanie propusă."
        )
    if text in _RESTART_COSTS:
        for field in _COST_FIELDS:
            setattr(account, field, None)
        return _start(session, account)
    if text in _RESTART_AREA:
        for field in _AREA_FIELDS:
            setattr(account, field, "")
        account.location_lat = account.location_lng = None
        account.max_travel_km = account.target_radius_km = None
        return _start(session, account)

    if not account.intake_step:
        if account.economics_confirmed_at is None and any(word in text for word in _LAUNCH_WORDS):
            return _start(session, account, intro=True)
        return None

    if text in _CANCEL:
        account.intake_step = ""
        _save(session, account)
        return (
            "Bine, ne oprim aici; răspunsurile date rămân salvate. Prima campanie așteaptă "
            "restul cifrelor - scrie «actualizează costurile» sau propune o campanie și reluăm "
            "de unde am rămas."
        )
    step = _STEPS[account.intake_step]
    if "?" in message or text.startswith(("de ce", "pentru ce", "ce inseamna")):
        return f"{step.why} {step.question}"
    outcome = _apply(account, step.key, text, geocoder)
    if outcome is None:
        return f"Nu am înțeles răspunsul - de exemplu {step.example}. {step.question}"
    if outcome and step.key != "max_travel_km":  # o problema (adresa negasita, harta cazuta)
        return outcome
    reason = outcome
    following = _missing(account)
    if following is None:
        try:
            text_done = _finish(account, now())
        except EconomicsError:
            for field in _COST_FIELDS:
                setattr(account, field, None)
            account.intake_step = _missing(account) or ""
            _save(session, account)
            return (
                "Din cifrele tale, o vânzare nu lasă profit nici înainte de reclame - orice "
                "reclamă ar adăuga pierdere. Hai să le verificăm: "
                + (first_question(account) or "")
            )
        _save(session, account)
        return f"{reason} {text_done}".strip()
    account.intake_step = following
    _save(session, account)
    return f"{reason} {_STEPS[following].question}".strip()


def _start(session: Session, account: ClientAccount, *, intro: bool = False) -> str:
    step = _missing(account)
    if step is None:
        account.intake_step = ""
        _save(session, account)
        return "Am deja tot ce-mi trebuie. " + (
            summary(account, limits) if (limits := thresholds(account)) else ""
        )
    account.intake_step = step
    account.economics_confirmed_at = None
    _save(session, account)
    question = _STEPS[step].question
    return f"{_INTRO} {question}" if intro else question


def open_intake(session: Session, account: ClientAccount) -> str | None:
    """Porneste interviul de la prima intrebare fara raspuns (lansarea fara costuri)."""
    step = _missing(account)
    if step is None:
        return None
    account.intake_step = step
    _save(session, account)
    return _STEPS[step].question


def complete(session: Session, account: ClientAccount, now: datetime) -> str | None:
    """Dupa ce costurile vin din formular: pragurile, daca nu mai lipseste nimic."""
    if _missing(account) is not None:
        return None
    message = _finish(account, now)
    _save(session, account)
    return message


def radius_from_form(account: ClientAccount, max_km: Decimal | None) -> str:
    """Raza aleasa de consiliu cand zona vine din formular (nu din chat)."""
    choice = choose_radius(_kind(account), _size(account), max_km)
    account.max_travel_km = max_km
    account.target_radius_km = choice.radius_km
    return choice.reason


_SIZES: tuple[PlaceSize, ...] = ("oras_mare", "oras", "localitate_mica")
_KINDS: tuple[BusinessKind, ...] = ("zilnic", "programat", "destinatie", "livrare")


def _size(account: ClientAccount) -> PlaceSize:
    """Marimea salvata; fara ea (harta n-a stiut-o), un oras obisnuit."""
    return next((size for size in _SIZES if size == account.place_size), "oras")


def _kind(account: ClientAccount) -> BusinessKind:
    return next((kind for kind in _KINDS if kind == account.business_kind), "programat")


def _save(session: Session, account: ClientAccount) -> None:
    session.add(account)
    session.commit()
    session.refresh(account)


def launch_economics(account: ClientAccount, daily_budget: Decimal) -> dict[str, str] | None:
    """Pragurile, pentru avizul unei lansari: ce inseamna bugetul in vanzari."""
    limits = thresholds(account)
    if limits is None:
        return None
    needed = (daily_budget / limits.max_cac).quantize(Decimal("0.1"), ROUND_CEILING)
    unit = "comenzi" if account.objective is CampaignObjective.SALES else "clienți noi"
    note = (
        f"Campania e profitabilă cât timp un client costă sub {_ron(limits.max_cac)} lei în "
        f"reclame (ROAS peste {_ron(limits.break_even_roas)}): la {_ron(daily_budget)} lei pe zi, "
        f"cel puțin {_ron(needed)} {unit} pe zi."
    )
    payload = {
        "max_cac": str(limits.max_cac),
        "break_even_roas": str(limits.break_even_roas),
        "note": note,
    }
    if limits.max_cpl is not None:
        payload["max_cpl"] = str(limits.max_cpl)
    return payload


class FormError(ValueError):
    """Un raspuns din formular care nu se poate folosi (adresa negasita, fara profit)."""


def apply_form(
    session: Session,
    account: ClientAccount,
    updates: dict[str, object],
    *,
    geocoder: Geocoder,
    now: datetime,
) -> str | None:
    """Raspunsurile din formular, ca in chat; intoarce motivul razei, cand s-a ales acum.

    Raises:
        FormError: adresa nu e pe harta, harta nu raspunde, ori costurile nu lasa profit.
    """
    for field in _COST_FIELDS:
        if field in updates:
            setattr(account, field, updates[field])
    if "service_area" in updates:
        account.service_area = str(updates["service_area"] or "")
    address = updates.get("business_address")
    if isinstance(address, str) and address.strip() != account.business_address:
        try:
            place = geocoder(address.strip(), account.geo or "RO")
        except PpcAgentError as exc:
            raise FormError("harta nu răspunde acum - mai încearcă peste câteva minute") from exc
        if place is None:
            raise FormError("adresa nu e pe hartă - scrie strada, numărul și orașul")
        account.business_address = address.strip()
        account.location_lat = place.latitude
        account.location_lng = place.longitude
        account.location_label = place.label
        account.place_size = place.size
    if "business_kind" in updates:
        account.business_kind = str(updates["business_kind"] or "")
    reason = None
    if (
        account.service_area == "local"
        and account.location_lat is not None
        and account.business_kind
        and (
            {"business_address", "business_kind", "max_travel_km"} & updates.keys()
            or account.target_radius_km is None
        )
    ):
        limit = updates.get("max_travel_km", account.max_travel_km)
        reason = radius_from_form(account, limit if isinstance(limit, Decimal) else None)
    account.economics_confirmed_at = None
    if _missing(account) is None:
        if thresholds(account) is None:
            session.rollback()
            raise FormError(
                "din cifrele acestea, o vânzare nu lasă profit nici înainte de reclame - orice "
                "reclamă ar adăuga pierdere. Verifică prețul și costurile."
            )
        _finish(account, now)
    else:
        account.intake_step = account.intake_step and (_missing(account) or "")
    _save(session, account)
    return reason
