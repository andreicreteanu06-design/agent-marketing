"""Monitorizarea sintetica a tracking-ului: un Chromium real parcurge site-ul clientului.

Ruleaza DOAR in worker (ARQ: pasul ``tracking_contract`` din mentenanta de noapte,
per client, cu timeout-ul jobului) - niciodata intr-un endpoint FastAPI: un
browser tine zeci de secunde si sute de MB. Imaginea API-ului nici nu are
Playwright; importul e tarziu, iar lipsa lui da ``tested: False``, nu o eroare.

Fluxul: URL-ul de start se urmeaza intai prin transportul SSRF-safe (fiecare
redirect verificat); Chromium mobil (390x844, service workers blocati - ar ascunde
trafic de interceptare) deschide pagina finala cu ``domcontentloaded`` - nu
``networkidle``, site-urile moderne tin conexiuni deschise -, accepta
consimtamantul, apasa CTA-ul din contract si asteapta, pana la 8 s, evenimentele
asteptate. ``request``/``response``/``requestfailed`` inregistreaza traficul;
``services/tracking_contract.py`` il judeca; rezultatul intra in ``TrackingEvidence``.

Scutul SSRF al browserului (site-ul e al clientului, deci neincrezut):
- fiecare cerere a paginii (document, script, fetch, beacon) trece printr-o ruta
  care refuza schemele non-http(s), IP-urile interne si numele care se rezolva
  intern (DNS verificat, fail-closed);
- numele interne ale stivei (postgres, redis, api...) si ale metadatelor cloud nu
  se rezolva deloc in Chromium (``--host-resolver-rules``);
- pagina finala se verifica si dupa navigare.

ponytail: redirect-urile HTTP din INTERIORUL Chromium nu trec prin ruta (verificat:
Playwright vede doar prima cerere a lantului) - un redirect spre un IP intern scris
literal ar ajunge la el orb (continutul nu se pastreaza nicaieri). Upgrade, cand
conteaza: proxy de iesire sau politica de retea care blocheaza RFC1918/link-local.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from sqlmodel import Session

from ppc_agent_server.db import get_engine
from ppc_agent_server.models import ClientAccount, TrackingEvidence
from ppc_agent_server.services.tracking_contract import (
    DEFAULT_CONSENT_SELECTORS,
    DEFAULT_EVENTS,
    CollectHit,
    JourneyRecord,
    Platform,
    TrackingContract,
    evaluate_journey,
    parse_collect_hit,
    parse_events,
)
from seo_geo_agent.audit.safe_transport import SafeAsyncTransport, resolve_host
from seo_geo_agent.audit.url_policy import is_blocked_host, is_ip_literal, is_public_address

MOBILE_VIEWPORT = {"width": 390, "height": 844}
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1 AcMediaMonitor/1.0"
)
NAVIGATION_TIMEOUT_MS = 20_000
CONSENT_TIMEOUT_MS = 3_000
CLICK_TIMEOUT_MS = 5_000
#: Cat asteptam evenimentele dupa actiune - cele din contract opresc asteptarea mai devreme.
HIT_WAIT_SECONDS = 8.0
#: Numele pe care Chromium nu le rezolva niciodata: serviciile stivei si metadatele cloud.
_INTERNAL_NAMES = (
    "postgres", "redis", "api", "worker", "seo-geo", "site", "migrate", "localhost",
    "metadata", "metadata.google.internal",
)
_CHROMIUM_ARGS = (
    "--host-resolver-rules=" + ", ".join(f"MAP {name} ~NOTFOUND" for name in _INTERNAL_NAMES),
    # /dev/shm e mic in containere; fara asta, Chromium cade pe pagini grele.
    "--disable-dev-shm-usage",
)
_PLATFORMS: tuple[Platform, ...] = ("ga4", "meta")


def site_url(target_domain: str) -> str:
    """``https://exemplu.ro/`` din domeniul din Setari (salvat ca origine sau, vechi, ca nume)."""
    origin = target_domain.strip().rstrip("/")
    return f"{origin if '://' in origin else f'https://{origin}'}/"


def contract_for(account: ClientAccount) -> TrackingContract | None:
    """Contractul clientului, din Setari; ``None`` fara domeniu (n-are ce testa).

    O platforma intra in test cand clientul i-a scris evenimentele, sau cand e
    conectata (GA4 / cont Meta) - atunci se asteapta page_view / PageView.
    """
    if not account.target_domain.strip():
        return None
    ga4 = parse_events(account.ga4_expected_events) or (
        (DEFAULT_EVENTS["ga4"],) if account.ga4_property_id else ()
    )
    meta = parse_events(account.meta_expected_events) or (
        (DEFAULT_EVENTS["meta"],) if account.meta_ad_account_id else ()
    )
    consent = account.journey_consent_selector.strip()
    return TrackingContract(
        # ``journey_path`` e validat in Setari sa inceapa cu "/": ramane pe site-ul clientului.
        url=urljoin(site_url(account.target_domain), account.journey_path.strip() or "/"),
        cta_selector=account.journey_cta_selector.strip(),
        consent_selectors=(consent, *DEFAULT_CONSENT_SELECTORS)
        if consent
        else DEFAULT_CONSENT_SELECTORS,
        ga4_events=ga4,
        meta_events=meta,
    )


async def _host_is_public(host: str, port: int, cache: dict[str, bool]) -> bool:
    """Fail-closed: un nume care nu se poate rezolva sigur nu e public."""
    if host in cache:
        return cache[host]
    if not host or is_blocked_host(host):
        verdict = False
    elif is_ip_literal(host):
        verdict = is_public_address(host)
    else:
        try:
            addresses = await resolve_host(host, port)
        except (OSError, TimeoutError):
            addresses = []
        verdict = bool(addresses) and all(is_public_address(address) for address in addresses)
    cache[host] = verdict
    return verdict


async def _final_url(url: str, *, allow_private: bool) -> tuple[str, str | None]:
    """Lantul de redirect-uri, urmat prin transportul SSRF-safe (fiecare pas verificat).

    Chromium primeste doar capatul lantului: redirect-urile HTTP din interiorul lui
    nu trec prin ruta de mai jos (Playwright vede doar prima cerere a lantului).
    Un raspuns 4xx/5xx aici nu opreste testul - unele site-uri refuza clientii care
    nu sunt browsere; statusul care conteaza e cel vazut de Chromium.
    """
    transport = None if allow_private else SafeAsyncTransport()
    last_error: str | None = None
    for _ in range(2):  # o reincercare: un sughit de retea nu e un site cazut
        try:
            async with httpx.AsyncClient(
                transport=transport,
                follow_redirects=True,
                timeout=15.0,
                headers={"User-Agent": MOBILE_USER_AGENT},
            ) as client:
                response = await client.get(url)
            return str(response.url), None
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:300]
    return url, last_error


async def record_journey(
    contract: TrackingContract,
    *,
    allow_private: bool = False,
    fulfill: Mapping[str, int] | None = None,
) -> JourneyRecord:
    """Parcurge site-ul intr-un Chromium mobil real si inregistreaza tot ce a plecat spre GA4/Meta.

    ``allow_private`` si ``fulfill`` (host -> status raspuns local) exista doar pentru
    testele cu server local: productia le lasa implicite.

    Raises:
        ImportError: Playwright nu e instalat (imaginea API-ului) - apelantul raporteaza.
    """
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Request, Response, Route, async_playwright

    start, error = await _final_url(contract.url, allow_private=allow_private)
    if error is not None:
        return JourneyRecord(None, error, False, False, None, None)

    hits: dict[Request, CollectHit] = {}
    blocked: list[str] = []
    public: dict[str, bool] = {}

    async def guard(route: Route, request: Request) -> None:
        parts = urlsplit(request.url)
        host = (parts.hostname or "").lower()
        if fulfill is not None and host in fulfill:
            await route.fulfill(status=fulfill[host], body="")
            return
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if parts.scheme not in ("http", "https") or (
            not allow_private and not await _host_is_public(host, port, public)
        ):
            blocked.append(request.url[:200])
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    def on_request(request: Request) -> None:
        try:
            body = request.post_data
        except (UnicodeDecodeError, PlaywrightError):
            body = None
        hit = parse_collect_hit(request.url, body)
        if hit is not None:
            hits[request] = hit

    def on_response(response: Response) -> None:
        if response.request in hits:
            hits[response.request] = replace(hits[response.request], status=response.status)

    def on_failed(request: Request) -> None:
        if request in hits:
            hits[request] = replace(hits[request], failure=request.failure or "failed")

    def delivered() -> bool:
        return all(
            any(hit.delivered and event in hit.events for hit in hits.values())
            for platform in _PLATFORMS
            for event in contract.events(platform)
        )

    consent_found = consent_clicked = False
    cta_found: bool | None = None
    cta_clicked: bool | None = None
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=list(_CHROMIUM_ARGS))
        try:
            context = await browser.new_context(
                viewport=MOBILE_VIEWPORT,  # type: ignore[arg-type]
                user_agent=MOBILE_USER_AGENT,
                is_mobile=True,
                has_touch=True,
                service_workers="block",
                accept_downloads=False,
            )
            await context.route("**/*", guard)
            context.on("request", on_request)
            context.on("response", on_response)
            context.on("requestfailed", on_failed)
            page = await context.new_page()
            try:
                response = await page.goto(
                    start, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                return JourneyRecord(None, str(exc)[:300], False, False, None, None, (), blocked)
            status = response.status if response is not None else None
            final = urlsplit(page.url)
            if not allow_private and not await _host_is_public(
                (final.hostname or "").lower(), final.port or 443, public
            ):
                return JourneyRecord(
                    None, "navigarea a ajuns la o adresă internă", False, False, None, None,
                    (), blocked,
                )

            for selector in contract.consent_selectors:
                try:
                    button = page.locator(selector).first
                    if await button.count():
                        consent_found = True
                        await button.click(timeout=CONSENT_TIMEOUT_MS)
                        consent_clicked = True
                        break
                except PlaywrightError:
                    continue

            if contract.cta_selector:
                cta_clicked = False
                try:
                    cta = page.locator(contract.cta_selector).first
                    cta_found = await cta.count() > 0
                    if cta_found:
                        # click() asteapta sa fie vizibil, activ si stabil: "interactiv".
                        await cta.click(timeout=CLICK_TIMEOUT_MS)
                        cta_clicked = True
                except PlaywrightError:
                    cta_found = bool(cta_found)

            deadline = asyncio.get_running_loop().time() + HIT_WAIT_SECONDS
            while not delivered() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.25)
        finally:
            await browser.close()
    return JourneyRecord(
        status, None, consent_found, consent_clicked, cta_found, cta_clicked,
        list(hits.values()), blocked,
    )


JourneyRecorder = Callable[[TrackingContract], Coroutine[Any, Any, JourneyRecord]]


def _hit_evidence(hit: CollectHit) -> dict[str, Any]:
    return {
        "platform": hit.platform,
        "events": list(hit.events),
        "tag_id": hit.tag_id,
        "status": hit.status,
        "failure": hit.failure,
    }


def run_tracking_contract_job(
    *, client_account_id: int, record: JourneyRecorder | None = None
) -> dict[str, Any]:
    """Testul sintetic E2E al unui client, salvat ca pachet de dovezi (``TrackingEvidence``).

    ``record`` e injectabil (teste); implicit, :func:`record_journey`, citit la apel
    (``tests_server/conftest.py`` il inlocuieste, ca nicio suita sa nu porneasca un browser).
    """
    with Session(get_engine()) as session:
        account = session.get(ClientAccount, client_account_id)
        if account is None:
            raise LookupError(f"clientul {client_account_id} nu exista")
        contract = contract_for(account)
        if contract is None:
            return {"tested": False, "reason": "fara domeniu in Setari"}
        started = datetime.now(tz=UTC)
        try:
            journey = asyncio.run((record or record_journey)(contract))
        except ImportError:
            return {"tested": False, "reason": "Playwright indisponibil (ruleaza doar in worker)"}
        verdict = evaluate_journey(contract, journey)
        evidence = TrackingEvidence(
            client_account_id=client_account_id,
            url=contract.url,
            started_at=started,
            finished_at=datetime.now(tz=UTC),
            navigation_status=journey.navigation_status,
            cta_selector=contract.cta_selector,
            cta_ok=verdict.journey_ok,
            ga4_transport_ok=verdict.ga4.transport_ok if verdict.ga4 else None,
            meta_transport_ok=verdict.meta.transport_ok if verdict.meta else None,
            failure_reason=verdict.failure_reason,
            evidence={
                "verdict": verdict.model_dump(mode="json"),
                "navigation_error": journey.navigation_error,
                "consent": {"found": journey.consent_found, "clicked": journey.consent_clicked},
                "cta": {"found": journey.cta_found, "clicked": journey.cta_clicked},
                "hits": [_hit_evidence(hit) for hit in journey.hits],
                "blocked_requests": list(journey.blocked),
            },
        )
        session.add(evidence)
        session.commit()
        return {
            "tested": True,
            "url": contract.url,
            "failure_reason": verdict.failure_reason,
            "ga4_transport_ok": evidence.ga4_transport_ok,
            "meta_transport_ok": evidence.meta_transport_ok,
        }
