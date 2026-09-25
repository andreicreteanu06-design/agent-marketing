"""Tehnicianul (CTO-ul): infrastructura de conversie a clientului, cu drept de veto.

Al treilea membru al consiliului Reginei (``council.py``). Strategul judeca
brandul, CFO-ul banii; Tehnicianul judeca daca cifrele pe care le judeca ei sunt
adevarate si daca site-ul poate converti traficul platit:

1. **Tracking-ul.** Fiecare flux de conversii (conversiile Google Ads, comenzile
   si apelurile trimise prin webhook) vine ca serie zilnica. Conversiile care se
   opresc brusc - zile la rand cu zero, desi ritmul de dinainte spune ca ar fi
   trebuit sa vina cel putin trei (Poisson: sub 5% sansa sa fie intamplare) -
   sunt o problema tehnica, nu una de marketing. Cand fluxul raporteaza si
   click-uri, ele despart cele doua cazuri: click-urile merg si conversiile nu ->
   tracking-ul e picat; au scazut si click-urile -> reclamele livreaza mai putin,
   tracking-ul nu e de vina. Sute de click-uri fara nicio conversie, niciodata:
   tag-ul nu e instalat sau formularul nu trimite.
2. **Viteza pe mobil** (Core Web Vitals): ultima masuratoare PageSpeed Insights
   pe mobil a agentului SEO/GEO, salvata noaptea (``SiteSpeedSample``). Pragurile
   sunt ale Google: LCP bun pana la 2,5 s, slab peste 4 s; CLS 0,1 si 0,25; TBT
   (proxy-ul de laborator pentru INP) 200 si 600 ms; scorul 90 si 50.

Veto-ul (:data:`VetoScope`): tracking picat -> ``money``, nicio decizie care
citeste conversiile (buget, canal nou, teste platite, reclame "care pierd",
cuvinte negative) - s-ar lua pe cifre false. Site lent pe mobil -> ``spend``,
nicio cheltuiala in plus (buget, canal nou, teste platite): ar plati click-uri
care pleaca inainte sa vada oferta. Rescrierile si excluderile trec oricum.

Fara aleator si fara LLM: aceleasi date dau acelasi raport, iar fiecare verdict
isi arata dovada in cifre. Fara date, starea e ``unknown`` - nu se ghiceste.
Pixelul Meta si GA4 nu trimit inca serii zilnice in platforma, deci nu se
"verifica" - loader-ul spune asta intr-o nota, nu inventeaza o stare.

Modulul e pur: fara DB, fara HTTP. Datele vin printr-un
:class:`TechnicalSignalsSource` (implementarea din baza de date: ``queen_signals.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from ppc_agent_server.services.humanizer import ENGINEER_VOICE
from ppc_agent_server.services.ro_format import count as _count

HealthStatus = Literal["green", "amber", "red", "unknown"]
TrackingFinding = Literal[
    "ok", "conversions_stopped", "traffic_stopped", "never_converted", "too_little_data"
]
SpeedRating = Literal["good", "needs_improvement", "poor"]
SpeedMetricKey = Literal["lcp", "cls", "tbt", "performance_score"]
#: ``money``: nicio decizie pe bani (tracking picat); ``spend``: nicio cheltuiala
#: in plus (site lent pe mobil); ``none``: fara veto.
VetoScope = Literal["none", "spend", "money"]

#: Atatea zile la rand fara nicio conversie, minim, ca sa vorbim de o oprire.
SILENCE_MIN_DAYS = 3
#: Cate conversii ar fi trebuit sa vina in zilele tacute, dupa ritmul de dinainte,
#: ca tacerea sa nu mai fie intamplare (Poisson: P(0 | 3 asteptate) ~ 5%).
EXPECTED_MISSING_MIN = 3.0
#: Sub atatea conversii inainte de pauza, ritmul e zgomot.
MIN_BASELINE_CONVERSIONS = 5
#: Click-urile din zilele tacute, fata de ritmul de dinainte: de la atat in sus,
#: traficul "a continuat" si vina e a tracking-ului, nu a livrarii.
TRAFFIC_KEPT_RATIO = 0.5
#: Atatea click-uri in fereastra, fara nicio conversie: tag-ul lipseste sau
#: formularul nu trimite (la o rata de 1%, sansa sa fie intamplare e ~5%).
NEVER_CONVERTED_MIN_CLICKS = 300
#: O masuratoare PageSpeed mai veche de atat nu mai spune cum e site-ul azi.
SPEED_MAX_AGE_DAYS = 14

STATUS_WORDS: dict[HealthStatus, str] = {
    "green": "verde",
    "amber": "galben",
    "red": "roșu",
    "unknown": "necunoscut",
}
#: Ordinea "cel mai grav primul" pentru starea de ansamblu: o stare verde cere
#: ca ambele verificari sa fie verzi, nu doar sa nu fie rosii.
_SEVERITY: dict[HealthStatus, int] = {"red": 3, "amber": 2, "unknown": 1, "green": 0}

# --- datele (ce primeste Tehnicianul) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class DailyConversions:
    """O zi dintr-un flux de conversii."""

    day: date
    conversions: float
    #: Click-urile platite din aceeasi zi; ``None`` = fluxul nu raporteaza trafic.
    clicks: int | None = None


@dataclass(frozen=True, slots=True)
class TrackingStream:
    """Un flux de conversii, zi de zi, pe toata fereastra (inclusiv zilele cu zero)."""

    #: ``google_ads`` sau sursa webhook-ului (``gomag``, ``call_tracker``...).
    key: str
    days: Sequence[DailyConversions]


@dataclass(frozen=True, slots=True)
class MobileSpeed:
    """Ultima masuratoare PageSpeed Insights, strategia mobil."""

    url: str
    measured_at: datetime
    performance_score: int | None
    lcp_ms: int | None
    cls: float | None
    tbt_ms: int | None


@dataclass(frozen=True, slots=True)
class TechnicalSignals:
    """Tot ce stie Tehnicianul despre un client."""

    #: Domeniul din Setari; gol = viteza nu are ce masura.
    domain: str
    #: Ziua curenta, incompleta: nu se judeca (conversiile ei inca vin).
    today: date
    streams: Sequence[TrackingStream]
    mobile_speed: MobileSpeed | None
    notes: Sequence[str] = ()


class TechnicalSignalsSource(Protocol):
    def load(self, client_account_id: int) -> TechnicalSignals: ...


# --- raportul ------------------------------------------------------------------------


class TrackingCheck(BaseModel):
    """Verdictul unui flux de conversii."""

    key: str
    label: str
    status: HealthStatus
    finding: TrackingFinding
    #: Ce s-a vazut, cu cifrele pe care se sprijina verdictul.
    evidence: str
    last_conversion: date | None
    #: Zilele complete, la rand, fara nicio conversie (cele mai recente).
    silent_days: int
    #: Reparatia, cand fluxul e rosu.
    fix: str | None


class SpeedMetric(BaseModel):
    key: SpeedMetricKey
    label: str
    #: Valoarea, scrisa ca in romana ("4,8 s", "0,31", "820 ms", "38 din 100").
    value: str
    #: Pragurile Google pentru metrica, in cuvinte.
    threshold: str
    rating: SpeedRating


class MobileSpeedCheck(BaseModel):
    """Verdictul vitezei pe mobil."""

    status: HealthStatus
    url: str | None
    measured_at: datetime | None
    metrics: list[SpeedMetric]
    evidence: str
    #: Reparatiile, in ordinea castigului, doar pentru metricile care nu sunt bune.
    fixes: list[str]


class TechnicianDirective(BaseModel):
    """Raportul Tehnicianului - calculat determinist, obligatoriu pentru consiliu."""

    client_account_id: int
    #: Starea de ansamblu: cea mai grava dintre tracking si viteza.
    status: HealthStatus
    tracking_status: HealthStatus
    speed_status: HealthStatus
    tracking: list[TrackingCheck]
    mobile_speed: MobileSpeedCheck
    veto: VetoScope
    veto_reason: str | None
    #: Pozitia Tehnicianului, in vocea lui (scurta, de inginer).
    summary: str
    #: Reparatiile, cele care ridica veto-ul primele.
    recommendations: list[str]
    notes: list[str]
    generated_at: datetime


# --- tracking-ul ---------------------------------------------------------------------

STREAM_LABELS: dict[str, str] = {
    "google_ads": "conversiile Google Ads",
    "gomag": "comenzile trimise de magazinul GoMag",
    "call_tracker": "apelurile din call tracking",
}
_TRACKING_FIXES: dict[str, str] = {
    "google_ads": (
        "Verifică tag-ul de conversie Google (gtag sau Google Tag Manager) pe pagina de "
        "mulțumire și, dacă folosești conversiile din GA4, importul lor în Google Ads."
    ),
    "gomag": (
        "Verifică webhook-ul de comenzi din GoMag: adresa, cheia de acces și ultimele livrări "
        "eșuate."
    ),
    "call_tracker": (
        "Verifică integrarea de call tracking: numărul afișat pe site și webhook-ul de apeluri."
    ),
}
_DEFAULT_TRACKING_FIX = (
    "Verifică sursa care trimite conversiile: tag-ul din site sau webhook-ul ei."
)
_TEST_CONVERSION = "Apoi fă o conversie de test cap-coadă și urmărește dacă ajunge."

_MONTHS = (
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
    "septembrie", "octombrie", "noiembrie", "decembrie",
)


def _day(value: date) -> str:
    """"20 septembrie" - ziua in cuvinte, fara cifre de luna pe care un LLM sa le rescrie."""
    return f"{value.day} {_MONTHS[value.month - 1]}"


def _decimal(value: float, digits: int = 1) -> str:
    """2.14 -> "2,1"; 3.0 -> "3"."""
    return f"{value:.{digits}f}".replace(".", ",").rstrip("0").removesuffix(",")


def _days(count: int) -> str:
    return "o zi" if count == 1 else _count(count, "zile")


def _clicks(count: int) -> str:
    return "un click" if count == 1 else _count(count, "click-uri")


def _conversions(count: float) -> str:
    return _count(count, "conversii", "conversie")


def stream_label(key: str) -> str:
    return STREAM_LABELS.get(key, f"conversiile din sursa «{key}»")


def check_tracking(stream: TrackingStream, *, today: date) -> TrackingCheck:
    """Verdictul unui flux: conversiile ajung, s-au oprit, sau nu se poate spune."""
    days = sorted((day for day in stream.days if day.day < today), key=lambda day: day.day)
    label = stream_label(stream.key)
    fix = f"{_TRACKING_FIXES.get(stream.key, _DEFAULT_TRACKING_FIX)} {_TEST_CONVERSION}"

    def _check(
        status: HealthStatus,
        finding: TrackingFinding,
        evidence: str,
        *,
        last: date | None = None,
        silent: int = 0,
    ) -> TrackingCheck:
        return TrackingCheck(
            key=stream.key,
            label=label,
            status=status,
            finding=finding,
            evidence=evidence,
            last_conversion=last,
            silent_days=silent,
            fix=fix if status == "red" else None,
        )

    if not days:
        return _check("unknown", "too_little_data", "Nicio zi completă cu date.")
    clicks_known = all(day.clicks is not None for day in days)
    silent = 0
    for day in reversed(days):
        if day.conversions > 0:
            break
        silent += 1
    before = days[: len(days) - silent]
    quiet = days[len(days) - silent :]

    if not before:
        window = _days(len(days))
        clicks = sum(day.clicks or 0 for day in days)
        if clicks_known and clicks >= NEVER_CONVERTED_MIN_CLICKS:
            return _check(
                "red",
                "never_converted",
                f"{_clicks(clicks).capitalize()} în ultimele {window} și nicio conversie "
                "înregistrată: ori tag-ul nu e instalat, ori formularul nu trimite.",
                silent=silent,
            )
        return _check(
            "unknown",
            "too_little_data",
            f"Nicio conversie în ultimele {window}: nu am un ritm cu care să compar.",
            silent=silent,
        )

    last = before[-1].day
    if silent < SILENCE_MIN_DAYS:
        return _check("green", "ok", f"Conversiile ajung: ultima pe {_day(last)}.", last=last)
    baseline = sum(day.conversions for day in before)
    if baseline < MIN_BASELINE_CONVERSIONS:
        return _check(
            "unknown",
            "too_little_data",
            f"Nicio conversie în ultimele {_days(silent)}, dar înainte au fost doar "
            f"{_conversions(round(baseline, 2))}: prea puține ca să despart o oprire de o "
            "perioadă slabă.",
            last=last,
            silent=silent,
        )
    rate = baseline / len(before)
    expected = rate * silent
    pace = f"{_decimal(rate)} pe zi"
    if expected < EXPECTED_MISSING_MIN:
        return _check(
            "green",
            "ok",
            f"Ultima conversie pe {_day(last)}. Pauza de {_days(silent)} intră în ritmul obișnuit "
            f"de {pace}.",
            last=last,
            silent=silent,
        )
    missing = _conversions(int(expected))
    stopped = f"Nicio conversie în ultimele {_days(silent)} (ultima pe {_day(last)})"
    if clicks_known:
        clicks_before = sum(day.clicks or 0 for day in before) / len(before)
        clicks_quiet = sum(day.clicks or 0 for day in quiet)
        if clicks_before <= 0 or clicks_quiet / silent < TRAFFIC_KEPT_RATIO * clicks_before:
            return _check(
                "unknown",
                "traffic_stopped",
                f"{stopped}, dar au scăzut și click-urile: {_decimal(clicks_quiet / silent)} pe "
                f"zi, față de {_decimal(clicks_before)} înainte. Reclamele livrează mai puțin; "
                "tracking-ul nu e dovedit stricat.",
                last=last,
                silent=silent,
            )
        return _check(
            "red",
            "conversions_stopped",
            f"{stopped}, deși reclamele au adus {_clicks(clicks_quiet)}. Înainte veneau "
            f"{pace}, deci lipsesc cel puțin {missing}.",
            last=last,
            silent=silent,
        )
    return _check(
        "red",
        "conversions_stopped",
        f"{stopped}. Înainte veneau {pace}: lipsesc cel puțin {missing}, iar tăcerea asta nu e "
        "întâmplare.",
        last=last,
        silent=silent,
    )


def _tracking_status(checks: Sequence[TrackingCheck]) -> HealthStatus:
    statuses = {check.status for check in checks}
    if "red" in statuses:
        return "red"
    return "green" if "green" in statuses else "unknown"


# --- viteza pe mobil -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    key: SpeedMetricKey
    label: str
    good: float
    poor: float
    threshold: str
    #: Scorul creste cand e bine; timpii si deplasarile scad.
    higher_is_better: bool = False


_SPECS: dict[SpeedMetricKey, _MetricSpec] = {
    "lcp": _MetricSpec(
        "lcp", "LCP (cât durează până apare conținutul principal)", 2500, 4000,
        "bun până la 2,5 s, slab peste 4 s",
    ),
    "cls": _MetricSpec(
        "cls", "CLS (cât sare pagina în timp ce se încarcă)", 0.1, 0.25,
        "bun până la 0,1, slab peste 0,25",
    ),
    "tbt": _MetricSpec(
        "tbt", "TBT (cât timp e blocată pagina de scripturi)", 200, 600,
        "bun până la 200 ms, slab peste 600 ms",
    ),
    "performance_score": _MetricSpec(
        "performance_score", "Scorul PageSpeed", 90, 50, "bun de la 90, slab sub 50",
        higher_is_better=True,
    ),
}
_SPEED_FIXES: dict[SpeedMetricKey, str] = {
    "lcp": (
        "LCP: comprimă imaginea principală (WebP sau AVIF, la dimensiunea afișată), "
        "preîncarc-o și mută după conținutul de sus scripturile care blochează randarea."
    ),
    "cls": (
        "CLS: pune dimensiuni fixe pe imagini, bannere și iframe-uri și rezervă locul barei de "
        "cookie-uri."
    ),
    "tbt": (
        "TBT: amână scripturile terțe (chat, pixeli, widgeturi) cu defer sau până la prima "
        "interacțiune și împarte JavaScript-ul lung în bucăți mici."
    ),
    "performance_score": (
        "Scorul: deschide raportul PageSpeed pe mobil și ia oportunitățile în ordinea timpului "
        "câștigat."
    ),
}
_RATING_ORDER: dict[SpeedRating, int] = {"good": 0, "needs_improvement": 1, "poor": 2}
_STATUS_BY_RATING: dict[SpeedRating, HealthStatus] = {
    "good": "green",
    "needs_improvement": "amber",
    "poor": "red",
}


def _rate(spec: _MetricSpec, value: float) -> SpeedRating:
    if spec.higher_is_better:
        if value >= spec.good:
            return "good"
        return "poor" if value < spec.poor else "needs_improvement"
    if value <= spec.good:
        return "good"
    return "poor" if value > spec.poor else "needs_improvement"


def _metric_value(key: SpeedMetricKey, value: float) -> str:
    if key == "lcp":
        return f"{_decimal(value / 1000)} s"
    if key == "cls":
        return _decimal(value, 2) or "0"
    if key == "tbt":
        return f"{int(value)} ms"
    return f"{int(value)} din 100"


def _reading(metric: SpeedMetric) -> str:
    """"LCP 4,8 s" / "scor 38 din 100"."""
    name = "scor" if metric.key == "performance_score" else metric.key.upper()
    return f"{name} {metric.value}"


def check_mobile_speed(
    sample: MobileSpeed | None, *, today: date, domain: str = ""
) -> MobileSpeedCheck:
    """Verdictul vitezei pe mobil, pe pragurile Google."""

    def _unknown(evidence: str, measured: MobileSpeed | None = None) -> MobileSpeedCheck:
        return MobileSpeedCheck(
            status="unknown",
            url=measured.url if measured else None,
            measured_at=measured.measured_at if measured else None,
            metrics=[],
            evidence=evidence,
            fixes=[],
        )

    if sample is None:
        if not domain:
            return _unknown("Viteza pe mobil nu se poate măsura: domeniul site-ului lipsește.")
        return _unknown(
            "Viteza pe mobil nu e măsurată încă: măsurătoarea PageSpeed rulează noaptea."
        )
    if (today - sample.measured_at.date()).days > SPEED_MAX_AGE_DAYS:
        return _unknown(
            f"Ultima măsurătoare PageSpeed e din {_day(sample.measured_at.date())}, prea veche ca "
            "să spună cum se încarcă site-ul azi.",
            sample,
        )
    values: tuple[tuple[SpeedMetricKey, float | None], ...] = (
        ("lcp", sample.lcp_ms),
        ("cls", sample.cls),
        ("tbt", sample.tbt_ms),
        ("performance_score", sample.performance_score),
    )
    metrics = [
        SpeedMetric(
            key=key,
            label=_SPECS[key].label,
            value=_metric_value(key, value),
            threshold=_SPECS[key].threshold,
            rating=_rate(_SPECS[key], value),
        )
        for key, value in values
        if value is not None
    ]
    if not metrics:
        return _unknown("Măsurătoarea PageSpeed nu a întors nicio metrică.", sample)

    worst = max((metric.rating for metric in metrics), key=_RATING_ORDER.__getitem__)
    weak = [metric for metric in metrics if metric.rating != "good"]
    score = next((m for m in metrics if m.key == "performance_score"), None)
    if not weak:
        evidence = (
            "Pe mobil, pagina se încarcă bine: "
            f"{', '.join(_reading(metric) for metric in metrics)}."
        )
    else:
        slow = "lentă" if worst == "poor" else "la limită"
        details = ", ".join(
            f"{_reading(metric)} ({metric.threshold})"
            for metric in weak
            if metric.key != "performance_score"
        )
        evidence = f"Pe mobil, pagina e {slow}" + (f": {details}." if details else ".")
        if score is not None:
            evidence += f" Scor PageSpeed: {score.value}."
    causes = [metric.key for metric in weak if metric.key != "performance_score"]
    fixes = [_SPEED_FIXES[key] for key in causes] or (
        [_SPEED_FIXES["performance_score"]] if weak else []
    )
    return MobileSpeedCheck(
        status=_STATUS_BY_RATING[worst],
        url=sample.url,
        measured_at=sample.measured_at,
        metrics=metrics,
        evidence=evidence,
        fixes=fixes,
    )


# --- raportul complet --------------------------------------------------------------


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} și {items[-1]}"


def evaluate_technical_health(
    client_account_id: int, signals: TechnicalSignals, *, generated_at: datetime
) -> TechnicianDirective:
    """Raportul Tehnicianului din date - functie pura, determinista."""
    tracking = [check_tracking(stream, today=signals.today) for stream in signals.streams]
    tracking_status = _tracking_status(tracking)
    speed = check_mobile_speed(signals.mobile_speed, today=signals.today, domain=signals.domain)
    broken = [check for check in tracking if check.status == "red"]

    veto: VetoScope = "none"
    veto_reason: str | None = None
    if broken:
        veto = "money"
        veto_reason = (
            f"Tracking-ul e picat pe {_join([check.label for check in broken])}: orice decizie "
            "pe bani s-ar lua pe cifre false."
        )
    elif speed.status == "red":
        veto = "spend"
        readings = ", ".join(
            _reading(metric) for metric in speed.metrics if metric.rating == "poor"
        )
        veto_reason = (
            f"Site-ul e lent pe mobil ({readings}): trafic plătit în plus ar plăti click-uri care "
            "pleacă înainte să vadă oferta."
        )

    recommendations = [check.fix for check in broken if check.fix]
    if not signals.streams:
        recommendations.append(
            "Conectează o sursă de conversii (contul Google Ads sau webhook-ul magazinului): fără "
            "ea, tracking-ul nu se poate verifica."
        )
    if speed.status in ("red", "amber"):
        recommendations.extend(speed.fixes)
    elif signals.mobile_speed is None and not signals.domain:
        recommendations.append(
            "Completează domeniul site-ului în Setări: viteza se măsoară noaptea."
        )

    notes = list(signals.notes)
    if not signals.streams:
        notes.append(
            "Nicio sursă de conversii: nici conversii Google Ads, nici comenzi sau apeluri "
            "trimise prin webhook."
        )
    status = max((tracking_status, speed.status), key=_SEVERITY.__getitem__)
    directive = TechnicianDirective(
        client_account_id=client_account_id,
        status=status,
        tracking_status=tracking_status,
        speed_status=speed.status,
        tracking=tracking,
        mobile_speed=speed,
        veto=veto,
        veto_reason=veto_reason,
        summary="",
        recommendations=recommendations,
        notes=notes,
        generated_at=generated_at,
    )
    directive.summary = technician_position(directive)
    return directive


# --- vocea (pozitia determinista, faptele, promptul) ----------------------------------

_VETO_LINES: dict[VetoScope, str] = {
    "money": "Veto pe orice decizie de buget până se repară tracking-ul.",
    "spend": "Veto pe orice cheltuială în plus până se repară viteza pe mobil.",
    "none": "",
}


def technician_position(directive: TechnicianDirective) -> str:
    """Ce spune Tehnicianul fara LLM: diagnosticul, veto-ul, prima reparatie."""
    tracking = directive.tracking
    broken = [check for check in tracking if check.status == "red"]
    word = STATUS_WORDS[directive.tracking_status]
    if broken:
        parts = [f"Tracking: {word}.", *(check.evidence for check in broken[:2])]
    elif directive.tracking_status == "green":
        parts = [f"Tracking: {word}. Conversiile ajung."]
    elif tracking:
        parts = [f"Tracking: {word}.", tracking[0].evidence]
    else:
        parts = [f"Tracking: {word}. Nicio sursă de conversii conectată."]
    speed = directive.mobile_speed
    parts.append(f"Mobil: {STATUS_WORDS[speed.status]}. {speed.evidence}")
    if directive.veto != "none":
        parts.append(_VETO_LINES[directive.veto])
    if directive.recommendations:
        first = directive.recommendations[0]
        parts.append(f"Întâi: {first if first[1:2].isupper() else first[:1].lower() + first[1:]}")
    return " ".join(parts)


def technician_facts(directive: TechnicianDirective) -> str:
    """Faptele Tehnicianului - singura lui sursa de adevar."""
    lines = [
        "Stare tracking (calculată determinist, obligatorie): "
        f"{STATUS_WORDS[directive.tracking_status]}."
    ]
    for check in directive.tracking:
        line = f"{check.label.capitalize()}: {STATUS_WORDS[check.status]}. {check.evidence}"
        lines.append(line)
    if not directive.tracking:
        lines.append("Nicio sursă de conversii conectată.")
    speed = directive.mobile_speed
    measured = f", măsurată pe {_day(speed.measured_at.date())}" if speed.measured_at else ""
    lines.append(
        f"Viteză pe mobil (PageSpeed{measured}, obligatorie): {STATUS_WORDS[speed.status]}. "
        f"{speed.evidence}"
    )
    lines.extend(
        f"{metric.label}: {metric.value}; pragul Google: {metric.threshold}."
        for metric in speed.metrics
    )
    lines.append(f"Veto (obligatoriu): {directive.veto_reason or 'niciunul'}")
    lines.extend(f"Reparație: {fix}" for fix in directive.recommendations)
    lines.extend(directive.notes)
    return "\n".join(f"- {line}" for line in lines)


TECHNICIAN_SYSTEM_PROMPT = (
    "Ești Tehnicianul (CTO-ul) din consiliul agenției AC Media: răspunzi de infrastructura de "
    "conversie a clientului, adică tracking-ul conversiilor și viteza site-ului pe mobil. "
    "Primești întrebarea clientului (proprietarul afacerii) și FAPTELE TEHNICE, calculate "
    "determinist.\n"
    "Reguli stricte:\n"
    "1. Judeci DOAR partea tehnică: ajung conversiile în platformă, se încarcă site-ul repede "
    "pe mobil? Brandul și rentabilitatea sunt treaba celorlalți membri.\n"
    "2. Stările din FAPTE (verde, galben, roșu, necunoscut) și veto-ul sunt obligatorii: nu le "
    "contrazici și nu le îndulcești. Dacă există veto, spui pe ce și de ce.\n"
    "3. Folosești DOAR FAPTELE. Nicio cifră, metrică sau prag care nu apare în ele. Dacă datele "
    "lipsesc, spui exact ce lipsește.\n"
    "4. Recomanzi reparația din FAPTE, cu componenta exactă. Nu pretinzi că ai reparat, "
    "instalat sau configurat ceva și nu promiți rezultate.\n"
    "5. Maximum 60 de cuvinte, text simplu, fără markdown, liste sau linkuri.\n\n"
    f"{ENGINEER_VOICE}"
)
