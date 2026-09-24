"""Date demonstrative pentru "Trafic & Pozitii", cand GA4 / Search Console nu sunt conectate.

Deterministe: aceeasi zi da aceleasi cifre la fiecare incarcare (seed = domeniu
+ data), ca graficul sa nu se schimbe la refresh, iar o zi are aceleasi cifre
in orice fereastra (7, 28 sau 90 de zile) in care apare.

Construite ca sa declanseze fiecare regula din ``intelligence.py``, ca pagina sa
arate ce face agentul: o pagina care pierde trafic, un cuvant cu CTR mic, unul
care a coborat, cuvinte pe pagina a doua, o pagina de pe care lumea pleaca
repede si cerere fara prezenta. Cuvintele sunt ale unui service auto - doar
ilustrative. Interfata le marcheaza MEREU drept demonstrative (``is_demo``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from seo_geo_agent.audit.geo_reporters import brand_token_from_url
from seo_geo_agent.services.intelligence import (
    EXPECTED_CTR,
    DailySearch,
    DailyTraffic,
    IntelligenceSources,
    PageTraffic,
    QueryStats,
    SourceKey,
    Window,
)

#: Luni..duminica: traficul unui business local scade clar in weekend.
_WEEKDAY = (1.08, 1.05, 1.03, 1.0, 0.94, 0.72, 0.66)
#: Cu cate zile inainte de "azi" incepe scaderea de trafic de pe pagina demo.
_DROP_DAYS = 21


def _rng(seed: str, salt: str, day: date) -> random.Random:
    # Seed din sir: Python il trece prin SHA-512, deci e stabil intre rulari
    # (nu depinde de PYTHONHASHSEED, ca hash()).
    return random.Random(f"{seed}:{salt}:{day.isoformat()}")


@dataclass(frozen=True, slots=True)
class _DemoPage:
    path: str
    share: float
    engagement: float
    #: Cota de trafic ramasa dupa inceputul scaderii (1 = fara scadere).
    after_drop: float = 1.0


_PAGES = (
    _DemoPage("/", 0.30, 0.64),
    _DemoPage("/schimb-ulei-cutie-automata", 0.19, 0.61, after_drop=0.45),
    _DemoPage("/diagnoza-auto", 0.12, 0.58),
    _DemoPage("/preturi", 0.11, 0.27),
    _DemoPage("/blog/semne-ulei-cutie-automata-uzat", 0.10, 0.52),
    _DemoPage("/vulcanizare", 0.09, 0.60),
    _DemoPage("/contact", 0.09, 0.71),
)


class DemoAnalyticsSource:
    """GA4 simulat: crestere lenta, weekenduri slabe, o pagina in scadere."""

    def __init__(self, seed: str, today: date) -> None:
        self._seed = seed
        self._today = today

    def _day(self, day: date) -> DailyTraffic:
        rng = _rng(self._seed, "ga4", day)
        days_ago = (self._today - day).days
        level = max(0.3, 1 - 0.0022 * days_ago) * 175
        sessions = round(level * _WEEKDAY[day.weekday()] * rng.uniform(0.88, 1.12))
        return DailyTraffic(
            day=day,
            sessions=sessions,
            pageviews=round(sessions * rng.uniform(1.7, 2.2)),
            engaged_sessions=round(sessions * rng.uniform(0.55, 0.66)),
        )

    def daily(self, window: Window) -> list[DailyTraffic]:
        return [self._day(day) for day in window.dates()]

    def pages(self, window: Window) -> list[PageTraffic]:
        drop_start = self._today - timedelta(days=_DROP_DAYS)
        totals = {page.path: [0, 0] for page in _PAGES}
        for traffic in self.daily(window):
            for page in _PAGES:
                share = page.share * (page.after_drop if traffic.day >= drop_start else 1.0)
                sessions = round(traffic.sessions * share)
                totals[page.path][0] += sessions
                totals[page.path][1] += round(sessions * page.engagement)
        return [
            PageTraffic(path=path, sessions=sessions, engaged_sessions=engaged)
            for path, (sessions, engaged) in totals.items()
        ]


@dataclass(frozen=True, slots=True)
class _DemoQuery:
    query: str
    position_now: float
    #: Pozitia de acum 28 de zile - intre cele doua, evolutie liniara.
    position_before: float
    impressions_per_day: float
    page: str
    #: Cat din CTR-ul obisnuit la pozitia lui obtine (sub 0.5 = "CTR mic").
    ctr_factor: float = 1.0


_BLOG_POST = "/blog/semne-ulei-cutie-automata-uzat"
_QUESTION_WHEN = "cand se schimba uleiul la cutia automata"
_QUESTION_PRICE = "cat costa schimbul de ulei la cutia automata"


def _demo_queries(brand: str) -> tuple[_DemoQuery, ...]:
    return (
        _DemoQuery(brand, 1.1, 1.2, 38, "/", ctr_factor=1.6),
        _DemoQuery(f"{brand} program", 1.4, 1.6, 9, "/contact", ctr_factor=1.5),
        _DemoQuery("schimb ulei cutie automata", 4.2, 3.9, 160, "/schimb-ulei-cutie-automata", 0.3),
        _DemoQuery("schimb ulei cutie automata pret", 6.1, 7.4, 55, "/preturi"),
        _DemoQuery("diagnoza auto computerizata", 9.4, 5.1, 70, "/diagnoza-auto"),
        _DemoQuery("service auto cutie automata", 12.6, 15.8, 95, "/schimb-ulei-cutie-automata"),
        _DemoQuery("ulei cutie automata", 14.2, 13.5, 120, _BLOG_POST),
        _DemoQuery("semne ulei cutie automata uzat", 3.1, 4.0, 40, _BLOG_POST),
        _DemoQuery("revizie auto pret", 8.6, 8.9, 45, "/preturi"),
        _DemoQuery("vulcanizare", 18.5, 21.0, 60, "/vulcanizare"),
        # Intrebari: primele doua - afisate mult, sus, fara click-uri (regula question_gap);
        # a treia e pe pagina 2, deci nu intra in regula.
        _DemoQuery(_QUESTION_WHEN, 5.6, 6.2, 135, "/schimb-ulei-cutie-automata", 0.22),
        _DemoQuery(_QUESTION_PRICE, 7.2, 7.8, 85, "/preturi", 0.3),
        _DemoQuery("ce ulei pentru cutie automata", 13.4, 14.0, 60, _BLOG_POST),
    )


#: Coada lunga: afisarile care nu intra in cuvintele de mai sus, ca totalul
#: zilnic sa arate ca in Search Console (mult mai mare decat suma topului).
_LONG_TAIL = _DemoQuery("(alte cuvinte)", 23.0, 24.5, 420, "")


def _ctr(position: float) -> float:
    rounded = max(1, round(position))
    if rounded in EXPECTED_CTR:
        return EXPECTED_CTR[rounded]
    return max(0.002, 0.012 * 11 / rounded)


class DemoSearchSource:
    """Search Console simulat, coerent cu cuvintele si paginile de mai sus."""

    def __init__(self, seed: str, today: date, brand: str) -> None:
        self._seed = seed
        self._today = today
        self._queries = _demo_queries(brand)

    def _query_day(self, query: _DemoQuery, day: date) -> tuple[int, int, float]:
        rng = _rng(self._seed, f"gsc:{query.query}", day)
        days_ago = (self._today - day).days
        drift = (query.position_before - query.position_now) * days_ago / 28
        position = min(60.0, max(1.0, query.position_now + drift + rng.uniform(-0.3, 0.3)))
        impressions = round(
            query.impressions_per_day * _WEEKDAY[day.weekday()] * rng.uniform(0.85, 1.15)
        )
        clicks = round(impressions * _ctr(position) * query.ctr_factor * rng.uniform(0.85, 1.15))
        return clicks, impressions, position

    def daily(self, window: Window) -> list[DailySearch]:
        rows: list[DailySearch] = []
        for day in window.dates():
            clicks = impressions = 0
            weighted = 0.0
            for query in (*self._queries, _LONG_TAIL):
                q_clicks, q_impressions, position = self._query_day(query, day)
                clicks += q_clicks
                impressions += q_impressions
                weighted += position * q_impressions
            rows.append(
                DailySearch(
                    day=day,
                    clicks=clicks,
                    impressions=impressions,
                    position=weighted / impressions if impressions else 0.0,
                )
            )
        return rows

    def queries(self, window: Window) -> list[QueryStats]:
        stats: list[QueryStats] = []
        for query in self._queries:
            clicks = impressions = 0
            weighted = 0.0
            for day in window.dates():
                q_clicks, q_impressions, position = self._query_day(query, day)
                clicks += q_clicks
                impressions += q_impressions
                weighted += position * q_impressions
            stats.append(
                QueryStats(
                    query=query.query,
                    clicks=clicks,
                    impressions=impressions,
                    position=weighted / impressions if impressions else 0.0,
                    page=query.page,
                )
            )
        return stats


class DemoVolumeSource:
    """Keyword Planner simulat: volumele cuvintelor de mai sus + idei fara prezenta."""

    def __init__(self, brand: str) -> None:
        self._volumes = {
            brand: 390,
            f"{brand} program": 70,
            "schimb ulei cutie automata": 2400,
            "schimb ulei cutie automata pret": 880,
            "diagnoza auto computerizata": 1600,
            "service auto cutie automata": 1300,
            "ulei cutie automata": 1900,
            "semne ulei cutie automata uzat": 170,
            "revizie auto pret": 1000,
            "vulcanizare": 12100,
            _QUESTION_WHEN: 590,
            _QUESTION_PRICE: 320,
            "ce ulei pentru cutie automata": 260,
            # Cerere fara nicio afisare a site-ului - regula content_gap.
            "reparatii cutie automata": 2900,
            "schimb ulei motor pret": 1300,
            "service auto weekend": 480,
        }

    def volumes(self, seeds: list[str]) -> dict[str, int]:
        return dict(self._volumes)


def demo_brand(domain: str) -> str:
    """Brandul din domeniu, pentru cuvintele de brand demonstrative."""
    return brand_token_from_url(domain if "://" in domain else f"https://{domain}") or "exemplu"


#: Ce scrie in dreptul fiecarei surse cand datele ei sunt demonstrative.
DEMO_NOTES: dict[SourceKey, str] = {
    "ga4": "Date demonstrative - conectează Google Analytics 4 din Integrări.",
    "gsc": "Date demonstrative - conectează Search Console din Integrări.",
    "keyword_planner": "Volume demonstrative, pe cuvintele demonstrative din Search Console.",
}


def demo_sources(domain: str, today: date) -> IntelligenceSources:
    """Toate cele trei surse demonstrative (niciuna conectata)."""
    seed = domain or "exemplu.ro"
    brand = demo_brand(domain)
    return IntelligenceSources(
        analytics=DemoAnalyticsSource(seed, today),
        analytics_status="demo",
        search=DemoSearchSource(seed, today, brand),
        search_status="demo",
        volumes=DemoVolumeSource(brand),
        volumes_status="demo",
        notes=dict(DEMO_NOTES),
    )
