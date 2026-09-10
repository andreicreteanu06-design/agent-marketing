"""Interfete abstracte pentru toti furnizorii de date externi.

Aceste clase definesc *ce* poate cere agentul, nu *cum* se obtin datele.
Implementari concrete: :mod:`ppc_agent.providers.mock` si
:mod:`ppc_agent.providers.live`.

Structurile de date tipizate returnate (``PageContext``, ``NegativeKeywordSet``,
etc.) se introduc odata cu modulele care le folosesc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Rezultatul brut al accesarii unei pagini de catre un crawler.

    Attributes:
        requested_url: URL-ul cerut initial.
        final_url: URL-ul final, dupa eventuale redirectari.
        status_code: Codul HTTP (``0`` daca cererea a esuat inainte de raspuns).
        html: Continutul HTML brut (sir gol daca nu exista).
        ok: Adevarat daca pagina a fost obtinuta si are continut utilizabil.
    """

    requested_url: str
    final_url: str
    status_code: int
    html: str
    ok: bool


class CrawlerProvider(ABC):
    """Acceseaza pagini web si expune ``robots.txt``-ul domeniului."""

    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """Obtine continutul paginii de la ``url``.

        Args:
            url: Adresa paginii de analizat.

        Returns:
            :class:`FetchResult` cu HTML-ul brut si metadatele raspunsului.
            Parsarea in ``PageContext`` se face in :mod:`ppc_agent.ingestion.crawler`.

        Raises:
            ppc_agent.errors.CrawlTimeoutError: Daca pagina nu raspunde la timp.
        """

    @abstractmethod
    def robots_txt(self, base_url: str) -> str | None:
        """Returneaza continutul ``robots.txt`` al domeniului, sau ``None``.

        Args:
            base_url: Originea domeniului (schema + host).

        Returns:
            Textul ``robots.txt``, sau ``None`` cand nu exista restrictii cunoscute
            (caz in care accesul este permis).
        """


class GscProvider(ABC):
    """Acces la datele Google Search Console."""

    @abstractmethod
    def top_queries(
        self, site_url: str, days: int = 90, min_impressions: int = 100
    ) -> pd.DataFrame:
        """Returneaza interogarile organice de top pentru un site.

        Args:
            site_url: Proprietatea GSC (ex. ``https://exemplu.ro/``).
            days: Fereastra de raportare, in zile.
            min_impressions: Prag minim de afisari pentru includere.

        Returns:
            ``DataFrame`` cu coloanele ``query``, ``clicks``, ``impressions``,
            ``ctr``, ``position``.
        """


class GbpProvider(ABC):
    """Acces la semnalele locale din Google Business Profile."""

    @abstractmethod
    def local_signals(self, location_id: str) -> dict[str, object]:
        """Returneaza numele entitatii, categoriile, recenziile si sentimentul.

        Args:
            location_id: Identificatorul locatiei in Google Business Profile.

        Returns:
            Dictionar cu nume, categorii, numar de recenzii, nota medie,
            mostre de recenzii si scor de sentiment per recenzie.
        """


class KeywordPlannerProvider(ABC):
    """Expansiune de cuvinte cheie prin Google Keyword Planner."""

    @abstractmethod
    def expand(self, seeds: list[str], geo: str, language: str) -> pd.DataFrame:
        """Extinde o lista de cuvinte cheie samanta.

        Args:
            seeds: Cuvinte cheie de pornire (din datele organice + crawling).
            geo: Cod de tara (ex. ``RO``).
            language: Cod de limba (ex. ``ro``).

        Returns:
            ``DataFrame`` cu coloanele ``keyword``, ``avg_monthly_searches``,
            ``competition``, ``low_top_bid``, ``high_top_bid``,
            ``match_type_suggestion``.
        """


class GoogleAdsProvider(ABC):
    """Acces la performanta campaniilor si la parcursurile de conversie Google Ads."""

    @abstractmethod
    def campaign_performance(self, customer_id: str) -> pd.DataFrame:
        """Performanta pe campanii / grupuri de anunturi.

        Args:
            customer_id: Identificatorul contului Google Ads.

        Returns:
            ``DataFrame`` cu coloanele ``arm_id``, ``name``, ``clicks``,
            ``conversions``, ``cost``, ``revenue`` (venitul din conversii).
        """

    @abstractmethod
    def conversion_paths(self, customer_id: str) -> list[list[str]]:
        """Parcursurile de client, ca liste de puncte de contact.

        Args:
            customer_id: Identificatorul contului Google Ads.

        Returns:
            Lista de parcursuri; fiecare este ``[canal1, canal2, ...,
            "conversion" | "null"]``.
        """


class MetaMarketingProvider(ABC):
    """Acces la seturile de reclame Meta pentru analiza de lichiditate."""

    @abstractmethod
    def ad_sets(self, ad_account_id: str) -> pd.DataFrame:
        """Returneaza seturile de reclame ale unui cont.

        Args:
            ad_account_id: Identificatorul contului de reclame Meta.

        Returns:
            ``DataFrame`` cu coloanele ``id``, ``audience_def``,
            ``weekly_conversions``, ``weekly_spend``, ``learning_phase``.
        """
