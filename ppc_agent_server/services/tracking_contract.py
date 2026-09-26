"""Contractul de tracking: ce trebuie sa livreze site-ul catre GA4 si Meta, si dovada.

Monitorizarea sintetica (``jobs/synthetic.py``) deschide site-ul intr-un Chromium
real (Playwright), accepta consimtamantul, apasa CTA-ul si inregistreaza tot
traficul. Aici, fara browser, se clasifica si se judeca:

- **GA4**: ``*.google-analytics.com/g/collect`` - ``en`` (numele evenimentului;
  ``_en`` acceptat si el) si ``tid`` (Measurement ID); un POST poate purta mai
  multe evenimente, cate unul pe linie.
- **Meta**: ``*.facebook.com/tr`` - ``ev`` (evenimentul) si ``id`` (Pixel ID), in
  query sau in corpul POST.

Un test trece NUMAI daca cererea a fost prinsa, evenimentul e cel din contract si
platforma a raspuns 2xx (204 No Content e perfect valid). Un script care doar s-a
incarcat nu dovedeste nimic. Esecul are un motiv exact (:data:`FailureReason`).

Modul pur: aceleasi inregistrari dau acelasi verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel

Platform = Literal["ga4", "meta"]
FailureReason = Literal[
    "SITE_UNAVAILABLE",
    "CRITICAL_JOURNEY_BROKEN",
    "NETWORK_FAILURE",
    "DATALAYER_MISSING",
    "EVENT_MISMATCH",
    "CONSENT_BLOCKED",
]

#: Butoanele de consimtamant ale celor mai folosite CMP-uri (OneTrust, Cookiebot,
#: Complianz, CookieYes). Unul configurat de client are prioritate.
DEFAULT_CONSENT_SELECTORS: tuple[str, ...] = (
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    ".cmplz-accept",
    ".cky-btn-accept",
)
#: Evenimentele implicite cand clientul are platforma, dar n-a spus ce eveniment asteapta.
DEFAULT_EVENTS: dict[Platform, str] = {"ga4": "page_view", "meta": "PageView"}
#: Ordinea gravitatii: primul motiv gasit e cel raportat.
_SEVERITY: tuple[FailureReason, ...] = (
    "SITE_UNAVAILABLE",
    "CRITICAL_JOURNEY_BROKEN",
    "NETWORK_FAILURE",
    "DATALAYER_MISSING",
    "EVENT_MISMATCH",
    "CONSENT_BLOCKED",
)


@dataclass(frozen=True, slots=True)
class TrackingContract:
    """Ce trebuie sa se intample pe site. ``()`` la o platforma = nu se testeaza."""

    url: str
    #: CTA-ul pe care se da click; gol = doar incarcarea paginii.
    cta_selector: str = ""
    consent_selectors: tuple[str, ...] = DEFAULT_CONSENT_SELECTORS
    ga4_events: tuple[str, ...] = ()
    meta_events: tuple[str, ...] = ()

    def events(self, platform: Platform) -> tuple[str, ...]:
        return self.ga4_events if platform == "ga4" else self.meta_events


@dataclass(frozen=True, slots=True)
class CollectHit:
    """O cerere catre platforma, cu ce s-a intamplat cu ea."""

    platform: Platform
    events: tuple[str, ...]
    tag_id: str
    #: Statusul HTTP al raspunsului; ``None`` = n-a venit niciun raspuns.
    status: int | None = None
    #: Motivul din ``requestfailed`` (ex. ``net::ERR_CONNECTION_RESET``).
    failure: str | None = None

    @property
    def delivered(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


@dataclass(frozen=True, slots=True)
class JourneyRecord:
    """Ce a vazut browserul, fara nicio interpretare."""

    #: Statusul navigarii initiale; ``None`` = n-a raspuns deloc.
    navigation_status: int | None
    navigation_error: str | None
    consent_found: bool
    consent_clicked: bool
    #: ``None`` cand contractul nu are CTA.
    cta_found: bool | None
    cta_clicked: bool | None
    hits: Sequence[CollectHit] = ()
    #: Cererile oprite de scutul SSRF al browserului.
    blocked: Sequence[str] = ()


def _values(params: dict[str, list[str]], *keys: str) -> list[str]:
    return [value for key in keys for value in params.get(key, []) if value]


def parse_collect_hit(url: str, post_data: str | None = None) -> CollectHit | None:
    """O cerere de colectare GA4 sau Meta, sau ``None`` pentru orice alt trafic."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    query = parse_qs(parts.query)
    if (host == "google-analytics.com" or host.endswith(".google-analytics.com")) and (
        parts.path.endswith("/g/collect")
    ):
        events = _values(query, "en", "_en")
        for line in (post_data or "").splitlines():
            events.extend(_values(parse_qs(line), "en", "_en"))
        tag = next(iter(_values(query, "tid")), "")
        return CollectHit("ga4", tuple(events), tag)
    if (host == "facebook.com" or host.endswith(".facebook.com")) and (
        parts.path.rstrip("/") == "/tr"
    ):
        body = parse_qs(post_data or "")
        events = _values(query, "ev") + _values(body, "ev")
        tag = next(iter(_values(query, "id") + _values(body, "id")), "")
        return CollectHit("meta", tuple(events), tag)
    return None


class PlatformVerdict(BaseModel):
    platform: Platform
    expected_events: list[str]
    tag_id: str | None
    events_seen: list[str]
    #: ``True`` = toate evenimentele din contract au ajuns cu 2xx; ``None`` = nejudecat
    #: (consimtamantul a blocat totul - nu e o dovada de tracking stricat).
    transport_ok: bool | None
    reason: FailureReason | None


class EvidenceVerdict(BaseModel):
    site_ok: bool
    #: ``None`` cand contractul nu are CTA.
    journey_ok: bool | None
    ga4: PlatformVerdict | None
    meta: PlatformVerdict | None
    failure_reason: FailureReason | None


def _platform_verdict(
    platform: Platform, expected: tuple[str, ...], record: JourneyRecord
) -> PlatformVerdict:
    hits = [hit for hit in record.hits if hit.platform == platform]
    seen = list(dict.fromkeys(event for hit in hits for event in hit.events))
    tag = next((hit.tag_id for hit in hits if hit.tag_id), None)

    def _verdict(ok: bool | None, reason: FailureReason | None) -> PlatformVerdict:
        return PlatformVerdict(
            platform=platform,
            expected_events=list(expected),
            tag_id=tag,
            events_seen=seen,
            transport_ok=ok,
            reason=reason,
        )

    if not hits:
        if record.consent_found and not record.consent_clicked:
            return _verdict(None, "CONSENT_BLOCKED")
        return _verdict(False, "DATALAYER_MISSING")
    missing = [
        event
        for event in expected
        if not any(hit.delivered and event in hit.events for hit in hits)
    ]
    if not missing:
        return _verdict(True, None)
    attempted = [hit for hit in hits if any(event in hit.events for event in missing)]
    if attempted:
        # Evenimentul a plecat din browser, dar platforma n-a confirmat cu 2xx.
        return _verdict(False, "NETWORK_FAILURE")
    return _verdict(False, "EVENT_MISMATCH")


def evaluate_journey(contract: TrackingContract, record: JourneyRecord) -> EvidenceVerdict:
    """Verdictul testului: site-ul, drumul (CTA-ul) si transportul catre fiecare platforma."""
    status = record.navigation_status
    site_ok = status is not None and 200 <= status < 300
    if not site_ok:
        return EvidenceVerdict(
            site_ok=False, journey_ok=None, ga4=None, meta=None, failure_reason="SITE_UNAVAILABLE"
        )
    journey_ok = None if not contract.cta_selector else bool(record.cta_clicked)
    platforms: tuple[Platform, ...] = ("ga4", "meta")
    verdicts = {
        platform: _platform_verdict(platform, contract.events(platform), record)
        for platform in platforms
        if contract.events(platform)
    }
    reasons = {verdict.reason for verdict in verdicts.values() if verdict.reason}
    if journey_ok is False:
        reasons.add("CRITICAL_JOURNEY_BROKEN")
    return EvidenceVerdict(
        site_ok=True,
        journey_ok=journey_ok,
        ga4=verdicts.get("ga4"),
        meta=verdicts.get("meta"),
        failure_reason=next((reason for reason in _SEVERITY if reason in reasons), None),
    )


def parse_events(raw: str) -> tuple[str, ...]:
    """``"page_view, generate_lead"`` -> ``("page_view", "generate_lead")``."""
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
