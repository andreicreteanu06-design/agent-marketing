"""Furnizori ``mock`` pentru datele Google: Search Console, Business Profile, Keyword Planner.

Datele sunt generate determinist dintr-un seed derivat din argumente (``hashlib``,
nu ``hash()`` care este randomizat intre procese). Fara apeluri de retea.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from ppc_agent.providers.base import (
    GbpProvider,
    GscProvider,
    KeywordPlannerProvider,
)
from ppc_agent.texttools import score_sentiment

_BASE_QUERIES: tuple[str, ...] = (
    "program facturare",
    "facturare online",
    "aplicatie facturi pfa",
    "emitere factura",
    "software facturare srl",
    "factura online gratis",
    "e-factura spv",
    "cont facturare",
    "ce este e-factura",
    "cum emit o factura",
    "program gestiune stocuri",
    "facturare si contabilitate",
    "aplicatie facturi telefon",
    "factura proforma model",
    "program facturare pret",
    "facturare abonament lunar",
    "jobs contabilitate",
    "curs facturare gratuit",
    "factura storno",
    "integrare api facturare",
)

_REVIEW_TEXTS: tuple[str, ...] = (
    "Aplicatie excelenta, emit facturile foarte rapid si suportul e amabil.",
    "Recomand, interfata simpla si e-Factura merge perfect.",
    "Bun raport calitate pret, dar mi-ar placea mai multe rapoarte.",
    "Serviciu ok, cateva intarzieri la sincronizarea cu SPV.",
    "Dezamagit de pret, a crescut fara notificare. Suport lent.",
    "Groaznic, aplicatia a picat exact la termenul de depunere.",
)


def _seed_int(*parts: str) -> int:
    digest = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _spread(seed: int, low: int, high: int) -> int:
    return low + (seed % (high - low + 1))


class MockGscProvider(GscProvider):
    """Google Search Console simulat: interogari organice de top."""

    def top_queries(
        self, site_url: str, days: int = 90, min_impressions: int = 100
    ) -> pd.DataFrame:
        """Genereaza ~20 interogari organice deterministe pentru ``site_url``.

        Coloane: ``query``, ``clicks``, ``impressions``, ``ctr``, ``position``.
        Nu aplica filtrul ``min_impressions`` — filtrarea se face in stratul de
        ingestie; parametrul este pastrat pentru compatibilitate cu interfata.
        """
        rows: list[dict[str, Any]] = []
        for index, query in enumerate(_BASE_QUERIES):
            seed = _seed_int(site_url, query)
            impressions = _spread(seed, 40, 5000)
            # Ancoram doua randuri exact pe granita 100 pentru vizibilitate.
            if index == 0:
                impressions = 100
            elif index == 1:
                impressions = 101
            position = 1.0 + (seed % 250) / 10.0
            ctr = round(max(0.002, 0.35 - position * 0.02), 4)
            clicks = int(impressions * ctr)
            rows.append(
                {
                    "query": query,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "position": round(position, 1),
                }
            )
        return pd.DataFrame(rows)


class MockGbpProvider(GbpProvider):
    """Google Business Profile simulat: semnale locale + sentiment pe recenzii."""

    def local_signals(self, location_id: str) -> dict[str, object]:
        """Genereaza semnale locale deterministe si scoruri de sentiment pe recenzii."""
        seed = _seed_int(location_id)
        count = _spread(seed, len(_REVIEW_TEXTS), 240)
        reviews: list[dict[str, object]] = []
        for text in _REVIEW_TEXTS:
            score, label = score_sentiment(text)
            reviews.append({"text": text, "score": score, "label": label})
        return {
            "name": "FacturarePro SRL",
            "categories": ["Software company", "Serviciu de contabilitate"],
            "review_count": count,
            "avg_rating": round(3.8 + (seed % 12) / 10.0, 1),
            "reviews": reviews,
        }


class MockKeywordPlannerProvider(KeywordPlannerProvider):
    """Google Keyword Planner simulat: expansiune de cuvinte cheie."""

    _MODIFIERS: tuple[str, ...] = (
        "{seed}",
        "pret {seed}",
        "{seed} online",
        "{seed} pentru firme",
        "cel mai bun {seed}",
        "aplicatie {seed}",
    )

    def expand(self, seeds: list[str], geo: str, language: str) -> pd.DataFrame:
        """Extinde fiecare samanta in cateva variante deterministe.

        Coloane: ``keyword``, ``avg_monthly_searches``, ``competition``,
        ``low_top_bid``, ``high_top_bid``, ``match_type_suggestion``.
        """
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for seed_kw in seeds:
            for template in self._MODIFIERS:
                keyword = template.format(seed=seed_kw).strip()
                if keyword in seen:
                    continue
                seen.add(keyword)
                seed = _seed_int(keyword, geo, language)
                competition = round((seed % 100) / 100.0, 2)
                low_bid = round(0.5 + (seed % 40) / 20.0, 2)
                rows.append(
                    {
                        "keyword": keyword,
                        "avg_monthly_searches": _spread(seed, 20, 18000),
                        "competition": competition,
                        "low_top_bid": low_bid,
                        "high_top_bid": round(low_bid * (1.6 + competition), 2),
                        "match_type_suggestion": "exact" if competition < 0.5 else "phrase",
                    }
                )
        return pd.DataFrame(rows)
