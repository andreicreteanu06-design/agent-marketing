"""Crawler live pentru Modulul 1, construit peste motorul de audit SEO/GEO.

Agentul de SEO/GEO are deja un crawler real, cu tot ce trebuie ca sa intre pe
un site strain fara sa faca rau: validare anti-SSRF a tintei, plafon de octeti,
antete si user-agent proprii, si - cel mai important - clasificarea ONESTA a
raspunsului (``ok``/``blocked``/``rate_limited``/``error``). Agentul PPC avea in
locul lui un stub care ridica ``SetupRequiredError``, ceea ce bloca tot Modulul
1 in modul ``live``.

Modulul asta e puntea intre ele. NU reimplementeaza nimic: importa din
``seo_geo_agent.audit`` validarea, plafonul si clasificarea, si le traduce in
contractul pe care il asteapta ``ppc_agent`` (:class:`FetchResult` cu HTML brut,
fiindca ``ingestion/crawler.py`` isi face singur parsarea in ``PageContext``,
cu alte campuri decat auditul - CTA-uri, elemente de navigatie, candidati de USP).

Doua lucruri pe care le pastreaza deliberat de la audit:

1. **Blocat nu inseamna gol.** Cand site-ul ne opreste, ridicam
   :class:`CrawlBlockedError`, nu intoarcem o pagina goala. Altfel Quality
   Score-ul ar raporta "landing page fara continut" pentru o pagina perfect
   buna pe care pur si simplu n-am putut-o citi.
2. **Tinta se valideaza inainte de cerere.** URL-ul unei pagini de destinatie
   vine din datele clientului, deci nu e de incredere.

Descarcarea e ``async`` (asa e si in audit), dar Modulul 1 e sincron, deci
puntea se face intr-un singur loc, cu ``asyncio.run`` - la fel ca la
``search_data/serp_tracker.py::check_rankings_sync``.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urljoin

import httpx

from ppc_agent.errors import (
    CrawlBlockedError,
    CrawlError,
    CrawlTargetBlockedError,
    CrawlTimeoutError,
)
from ppc_agent.providers import base
from seo_geo_agent.audit.crawler import (
    CRAWL_HEADERS,
    MAX_HTML_BYTES,
    classify_fetch,
    read_text_up_to,
)
from seo_geo_agent.audit.safe_transport import SafeAsyncTransport, SsrfBlockedError
from seo_geo_agent.audit.types import CRAWL_USER_AGENT
from seo_geo_agent.audit.url_policy import is_crawlable_url

logger = logging.getLogger("ppc_agent.providers.live.crawler")

_DEFAULT_TIMEOUT = 15.0
#: ``robots.txt`` e un fisier text mic; nu are rost sa citim un megaoctet din el.
_MAX_ROBOTS_BYTES = 128 * 1024
#: Cate redirecturi urmarim. Auditul le urmareste manual, ca sa inregistreze
#: fiecare salt; aici ne intereseaza doar pagina finala, deci le lasam pe seama
#: lui httpx - dar marginite, ca o bucla sa nu ne tina la nesfarsit.
_MAX_REDIRECTS = 5


class LiveCrawlerProvider(base.CrawlerProvider):
    """Descarca pagini reale, folosind motorul de crawling al agentului SEO/GEO.

    Args:
        timeout: Secunde pana la abandonarea unei cereri.
        transport: Injectat in teste (``httpx.MockTransport``); ``None`` in
            productie, unde fiecare cerere - inclusiv fiecare salt de redirect -
            trece prin scutul SSRF (``SafeAsyncTransport``): DNS rezolvat de noi,
            nicio adresa interna, conexiune la IP-ul verificat.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    def _client(self, *, follow_redirects: bool) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport or SafeAsyncTransport(),
            timeout=self._timeout,
            follow_redirects=follow_redirects,
            max_redirects=_MAX_REDIRECTS,
        )

    def fetch(self, url: str) -> base.FetchResult:
        """Obtine HTML-ul brut al paginii de la ``url``.

        Args:
            url: Adresa paginii de analizat.

        Returns:
            :class:`~ppc_agent.providers.base.FetchResult` cu HTML-ul brut.
            ``ok=False`` cand pagina a raspuns, dar nu cu HTML utilizabil
            (404, document non-HTML, corp gol).

        Raises:
            CrawlTargetBlockedError: URL-ul tinta nu are voie sa fie accesat.
            CrawlTimeoutError: Pagina nu a raspuns la timp.
            CrawlBlockedError: Site-ul ne-a oprit (challenge anti-bot, 403, 429).
            CrawlError: Orice alt esec de retea.

        Toate patru sunt subclase de ``CrawlError``, pe care
        ``ingestion/crawler.py::crawl`` le prinde si le transforma intr-un
        ``PageContext`` cu ``ok=False`` - numele clasei ajunge in
        ``failure_reason``, deci motivul se vede pana in raport.
        """
        if not is_crawlable_url(url):
            raise CrawlTargetBlockedError(
                f"URL-ul '{url}' nu poate fi accesat: schema neacceptata sau adresa privata."
            )
        return asyncio.run(self._fetch(url))

    async def _fetch(self, url: str) -> base.FetchResult:
        async with self._client(follow_redirects=True) as client:
            try:
                request = client.build_request("GET", url, headers=CRAWL_HEADERS)
                response = await client.send(request, stream=True)
            except SsrfBlockedError as exc:
                raise CrawlTargetBlockedError(
                    f"'{url}' duce la o adresa care nu poate fi accesata: {exc}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise CrawlTimeoutError(f"'{url}' nu a raspuns in {self._timeout:.0f}s.") from exc
            except (httpx.HTTPError, UnicodeError, ValueError) as exc:
                raise CrawlError(f"'{url}' nu a putut fi accesat: {exc}") from exc

            try:
                html, _ = await read_text_up_to(response, MAX_HTML_BYTES)
            except httpx.TimeoutException as exc:
                raise CrawlTimeoutError(
                    f"'{url}' a raspuns, dar corpul nu s-a citit in {self._timeout:.0f}s."
                ) from exc
            except httpx.HTTPError as exc:
                raise CrawlError(f"corpul lui '{url}' nu a putut fi citit: {exc}") from exc
            finally:
                await response.aclose()

            fetch_class = classify_fetch(response.status_code, response.headers, html[:2048])
            if fetch_class in ("blocked", "rate_limited"):
                raise CrawlBlockedError(
                    f"site-ul a oprit crawler-ul pe '{url}' ({fetch_class}, "
                    f"status {response.status_code}) - pagina NU e goala, doar n-am putut-o citi."
                )

            content_type = response.headers.get("content-type", "")
            is_html = "html" in content_type.lower() or not content_type
            final_url = str(response.url)

        ok = 200 <= response.status_code < 300 and is_html and bool(html.strip())
        if not ok:
            logger.info(
                "pagina '%s' nu e HTML utilizabil (status %d, content-type '%s')",
                url,
                response.status_code,
                content_type,
            )
        return base.FetchResult(
            requested_url=url,
            final_url=final_url,
            status_code=response.status_code,
            html=html if is_html else "",
            ok=ok,
        )

    def robots_txt(self, base_url: str) -> str | None:
        """Continutul ``robots.txt`` al domeniului, sau ``None``.

        Args:
            base_url: Originea domeniului (schema + host).

        Returns:
            Textul fisierului, sau ``None`` cand lipseste ori nu e accesibil.

        ``None`` inseamna "nu stiu", iar ``RobotsPolicy`` il trateaza permisiv -
        acelasi comportament ca la orice crawler: lipsa unui ``robots.txt`` nu
        e o interdictie. Un esec de retea NU se propaga aici: nu vrem ca un
        ``robots.txt`` inaccesibil sa opreasca analiza intregii pagini.
        """
        robots_url = urljoin(base_url, "/robots.txt")
        if not is_crawlable_url(robots_url):
            return None
        return asyncio.run(self._robots_txt(robots_url))

    async def _robots_txt(self, robots_url: str) -> str | None:
        async with self._client(follow_redirects=True) as client:
            try:
                response = await client.get(
                    robots_url, headers={"User-Agent": CRAWL_USER_AGENT}
                )
            except (httpx.HTTPError, UnicodeError, ValueError) as exc:
                logger.warning("nu am putut citi %s: %s", robots_url, exc)
                return None
        if response.status_code != 200:
            return None
        return response.text[:_MAX_ROBOTS_BYTES]
