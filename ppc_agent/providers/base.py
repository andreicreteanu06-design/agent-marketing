"""Interfete abstracte pentru toti furnizorii de date externi.

Aceste clase definesc *ce* poate cere agentul, nu *cum* se obtin datele.
Implementari concrete: :mod:`ppc_agent.providers.mock` si
:mod:`ppc_agent.providers.live`.

Structurile de date tipizate returnate (``PageContext``, ``NegativeKeywordSet``,
etc.) se introduc odata cu modulele care le folosesc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


class CrawlerProvider(ABC):
    """Extrage structura si continutul unei pagini de destinatie."""

    @abstractmethod
    def fetch(self, url: str) -> dict[str, object]:
        """Descarca si parseaza ``url``.

        Args:
            url: Adresa paginii de analizat.

        Returns:
            Dictionar brut cu titlu, meta description, headings, texte CTA si
            structura de navigatie. Forma tipizata (``PageContext``) se adauga
            in Modulul 1.
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
