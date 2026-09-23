"""Furnizor live pentru Google Search Console (Modulul 1).

Nu are client propriu: foloseste :class:`~ppc_agent.search_data.search_console.
SearchConsoleClient`, scris pentru motorul hibrid PPC+SEO si testat acolo. Rolul
modulului asta e doar sa traduca intre contractul motorului hibrid (randuri
tipizate) si contractul Modulului 1 (``DataFrame`` cu cinci coloane).

Doua decizii care merita spuse:

1. **Proprietatea se ia din configuratie, nu din URL-ul paginii.** Search
   Console are doua tipuri de proprietati (``sc-domain:exemplu.ro`` si
   ``https://exemplu.ro/``), iar dintr-un domeniu simplu nu se poate ghici care
   dintre ele e verificata pe cont. Cand clientul a scris-o, o folosim pe a lui;
   altfel normalizam ce primim si spunem in eroare daca nu s-a nimerit.
2. **Se cere agregarea de la Google, nu istoricul zilnic.** ``top_queries`` are
   nevoie de totaluri pe interval, iar pozitia medie nu se poate reconstitui
   corect din randuri zilnice fara ponderare dupa afisari.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd

from ppc_agent.providers.base import GscProvider
from ppc_agent.search_data.search_console import SearchConsoleClient

#: Coloanele pe care le asteapta ``ingestion.organic.to_seed_keywords``.
_COLUMNS = ["query", "clicks", "impressions", "ctr", "position"]


class LiveGscProvider(GscProvider):
    """Interogarile organice reale ale unui site, din Search Console.

    Args:
        site_url: Proprietatea configurata de client (``sc-domain:exemplu.ro``
            sau ``https://exemplu.ro/``). Gol = se foloseste argumentul primit
            de :meth:`top_queries`.
        client_id: Client ID-ul OAuth al aplicatiei.
        client_secret: Client secret-ul OAuth.
        refresh_token: Refresh token cu scope ``webmasters.readonly``. ATENTIE:
            un token emis pentru ``adwords`` NU acopera Search Console - sunt
            doua consimtaminte diferite.
        timeout: Secunde pana la abandonarea unei cereri.
        transport: Injectat in teste; ``None`` in productie.
    """

    def __init__(
        self,
        *,
        site_url: str = "",
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._site_url = site_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._transport = transport

    def _client(self, fallback_site_url: str) -> SearchConsoleClient:
        return SearchConsoleClient(
            site_url=self._site_url or fallback_site_url,
            client_id=self._client_id,
            client_secret=self._client_secret,
            refresh_token=self._refresh_token,
            timeout=self._timeout,
            transport=self._transport,
        )

    def top_queries(
        self, site_url: str, days: int = 90, min_impressions: int = 100
    ) -> pd.DataFrame:
        """Interogarile organice de top ale ultimelor ``days`` zile.

        Args:
            site_url: Proprietatea, daca nu e deja configurata pe furnizor.
            days: Fereastra de raportare.
            min_impressions: Prag de includere (``>=``).

        Returns:
            ``DataFrame`` cu ``query``, ``clicks``, ``impressions``, ``ctr``,
            ``position``, sortat descrescator dupa afisari.

        Raises:
            SetupRequiredError: credentiale lipsa, proprietate neverificata sau
                scrisa gresit, Search Console inaccesibil.
            ProviderError: raspuns neasteptat de la API.

        ``end_date`` e ziua curenta, desi datele ultimelor zile nu sunt inca
        finalizate: clientul cere implicit ``dataState=final``, deci Google
        pur si simplu nu le intoarce. Nu scadem zile "de siguranta" - ar fi o
        aproximare in plus peste una pe care API-ul o face deja exact.
        """
        end_date = datetime.now(tz=UTC).date()
        totals = self._client(site_url).fetch_query_totals(
            start_date=end_date - timedelta(days=days), end_date=end_date
        )
        rows = [
            {
                "query": item.query,
                "clicks": item.clicks,
                "impressions": item.impressions,
                "ctr": round(item.ctr, 4),
                "position": round(item.position, 1),
            }
            for item in totals
            if item.impressions >= min_impressions
        ]
        frame = pd.DataFrame(rows, columns=_COLUMNS)
        if frame.empty:
            return frame
        return frame.sort_values("impressions", ascending=False, ignore_index=True)
