"""Trendurile saptamanii -> ``trends.json`` -> ``POST /api/v1/trends/ingest``.

Il ruleaza GitHub Actions in fiecare luni (``.github/workflows/trend_ingestion.yml``).
Python pur, doar biblioteca standard - pe runner nu se instaleaza nimic. Trendurile vin
din Meta Ad Library (:func:`meta_trends`): reclamele active in Romania de cel putin
``PROVEN_DAYS`` zile, pe industriile cautate - o reclama tinuta atata, de obicei, aduce
bani. Fara ``META_AD_LIBRARY_TOKEN`` pleaca datele de proba (:func:`sample_trends`).
Forma e ``TrendPayload`` din ``services/creative_context.py``.

Variabile de mediu:
    API_URL                adresa publica a API-ului (ex. https://api.exemplu.ro), HTTPS -
                           cheia pleaca in antet; http doar pentru localhost.
    CRON_SECRET_KEY        aceeasi valoare ca in .env-ul serverului (antetul X-Cron-Secret).
    META_AD_LIBRARY_TOKEN  optional, token Meta cu acces la Ad Library API (contul trebuie
                           sa aiba identitatea confirmata); expira - vezi README.
    TREND_SEARCH_TERMS     optional, industriile cautate, separate prin virgula
                           (implicit ``DEFAULT_TERMS``).
    TRENDS_FILE            optional, unde se scrie fisierul intermediar (implicit trends.json).

Coduri de iesire: 0 trimis; 1 Meta sau serverul a refuzat ori nu raspunde, sau Meta n-a
dat niciun trend; 2 lipsesc variabile.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

INGEST_PATH = "/api/v1/trends/ingest"
TIMEOUT_SECONDS = 60
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Versiunea din documentatia Ad Library (octombrie 2026); Meta retrage o versiune la ~2 ani.
ADS_ARCHIVE_URL = "https://graph.facebook.com/v26.0/ads_archive"
#: O reclama tinuta 3 saptamani se plateste, de obicei: cele care pierd bani se opresc.
PROVEN_DAYS = 21
#: Cele mai vazute reclame pastrate pe fiecare cautare (industrie x format).
PER_SEARCH = 2
MAX_TRENDS = 200  # limita lui TrendIngest
DEFAULT_TERMS = (
    "service auto",
    "stomatologie",
    "salon",
    "clinica",
    "magazin online",
    "curatenie",
)
_MEDIA = {"VIDEO": "Video", "IMAGE": "Imagine"}
_FIELDS = (
    "id,page_id,page_name,ad_creative_bodies,ad_creative_link_titles,ad_delivery_start_time,"
    "publisher_platforms,eu_total_reach"
)


def _de(number: int) -> str:
    """«21 de zile», dar «101 zile»: fara «de» cand ultimele doua cifre sunt 1-19."""
    return "" if 1 <= number % 100 <= 19 else "de "


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _texts(ad: dict[str, Any], key: str) -> list[str]:
    """Textele reale ale reclamei; sabloanele reclamelor dinamice ({{product.name}}) nu."""
    return [t for t in ad.get(key) or [] if isinstance(t, str) and t.strip() and "{{" not in t]


def _reach(ad: dict[str, Any]) -> int:
    reach = ad.get("eu_total_reach")
    return reach if isinstance(reach, int) and reach > 0 else 0


def search_terms() -> list[str]:
    terms = [t.strip() for t in os.getenv("TREND_SEARCH_TERMS", "").split(",") if t.strip()]
    return terms or list(DEFAULT_TERMS)


def fetch_ads(token: str, term: str, media: str, today: date) -> list[dict[str, Any]]:
    """Prima pagina de reclame active in Romania, pornite de cel putin ``PROVEN_DAYS`` zile.

    Raises:
        urllib.error.URLError: Meta refuza (token expirat...) sau nu raspunde.
    """
    query = urlencode(
        {
            "access_token": token,
            "ad_reached_countries": '["RO"]',
            "ad_active_status": "ACTIVE",
            "ad_delivery_date_max": (today - timedelta(days=PROVEN_DAYS)).isoformat(),
            "search_terms": term,
            "media_type": media,
            "fields": _FIELDS,
            "limit": "50",
        }
    )
    # Adresa contine tokenul: nu se scrie in log; erorile urllib nu o includ.
    with urllib.request.urlopen(f"{ADS_ARCHIVE_URL}?{query}", timeout=TIMEOUT_SECONDS) as r:
        body: dict[str, Any] = json.loads(r.read().decode("utf-8"))
    return [ad for ad in body.get("data") or [] if isinstance(ad, dict)]


def ad_trend(ad: dict[str, Any], term: str, media: str, today: date) -> dict[str, Any] | None:
    """O reclama dovedita -> ``TrendPayload``; ``None`` daca e prea noua sau fara text."""
    bodies = _texts(ad, "ad_creative_bodies")
    try:
        started = date.fromisoformat(str(ad.get("ad_delivery_start_time", ""))[:10])
    except ValueError:
        return None
    days = (today - started).days
    if not bodies or days < PROVEN_DAYS or not str(ad.get("id", "")).isdigit():
        return None
    first_line = re.split(r"(?<=[.!?…])\s|\n", bodies[0].strip(), maxsplit=1)[0]
    hook = _cut(first_line, 300)
    if len(hook) < 5:
        return None
    headline = (_texts(ad, "ad_creative_link_titles") or [hook])[0]
    page = str(ad.get("page_name") or "").strip() or "Un advertiser"
    platforms = ", ".join(
        str(p).replace("_", " ").title() for p in ad.get("publisher_platforms") or []
    )
    reach = _reach(ad)
    seen = f" (~{reach:,} {_de(reach)}oameni în UE)".replace(",", ".") if reach else ""
    media_name = _MEDIA[media]
    return {
        "title": _cut(f"{page}: {headline}", 120),
        "hook": hook,
        "visual_format": _cut(f"{media_name} pe {platforms}" if platforms else media_name, 120),
        "virality_reason": f"Rulează de {days} {_de(days)}zile în România{seen}: o reclamă "
        "ținută atâta, de obicei, aduce bani.",
        "platform": "meta",
        "industry": _cut(term, 120),
        # Nu ad_snapshot_url: aceea poate purta tokenul.
        "source": f"https://www.facebook.com/ads/library/?id={ad['id']}",
        "observed_at": today.isoformat(),
    }


def meta_trends(token: str, terms: list[str], today: date) -> list[dict[str, Any]]:
    """Cele mai vazute reclame dovedite, pe fiecare industrie si format; o reclama pe pagina.

    Raises:
        urllib.error.URLError: vezi :func:`fetch_ads`.
    """
    trends: dict[str, dict[str, Any]] = {}
    pages: set[str] = set()
    for term in terms:
        for media in _MEDIA:
            ads = sorted(
                fetch_ads(token, term, media, today),
                key=lambda ad: (-_reach(ad), str(ad.get("ad_delivery_start_time") or "9")),
            )
            kept = 0
            for ad in ads:
                trend = ad_trend(ad, term, media, today)
                page = str(ad.get("page_id") or ad.get("page_name") or "")
                if trend is None or page in pages or trend["title"] in trends:
                    continue
                trends[trend["title"]] = trend
                pages.add(page)
                kept += 1
                if kept == PER_SEARCH:
                    break
    return list(trends.values())[:MAX_TRENDS]


def sample_trends(today: date) -> list[dict[str, Any]]:
    """DATE DE PROBA - pleaca doar cand lipseste ``META_AD_LIBRARY_TOKEN``.

    Aceeasi forma ca ``TrendPayload``: titlu, hook, format vizual, de ce merge, platforma,
    industria (cuvinte cheie; gol = orice industrie), sursa, data observarii.
    """
    seen = (today - timedelta(days=2)).isoformat()
    return [
        {
            "title": "Mecanicul vorbeste direct in camera",
            "hook": "«Asta e piesa pe care ti-o schimba altii degeaba» - piesa in mana, din "
            "prima secunda.",
            "visual_format": "UGC 9:16, 20-30 s, filmat in atelier, subtitrari mari",
            "virality_reason": "Expertul real si dezvaluirea unei practici necinstite: "
            "incredere si curiozitate in acelasi timp.",
            "platform": "tiktok",
            "industry": "service auto, piese auto, reparatii",
            "source": "date de proba",
            "observed_at": seen,
        },
        {
            "title": "Inainte si dupa, in 3 secunde",
            "hook": "Rezultatul final apare primul, apoi «uite cum arata cand a venit».",
            "visual_format": "Reel 9:16, 12-15 s, taietura la 3 s, muzica in trend",
            "virality_reason": "Fenta vizuala: privitorul vede rezultatul si ramane sa afle "
            "de unde s-a pornit.",
            "platform": "meta",
            "industry": "salon, frizerie, cosmetica, curatenie",
            "source": "date de proba",
            "observed_at": seen,
        },
        {
            "title": "Pretul spus din prima",
            "hook": "«Cat costa, de fapt?» - cu suma pe ecran inainte de orice explicatie.",
            "visual_format": "Imagine 4:5 sau video 9:16 sub 10 s, cifra cat jumatate de ecran",
            "virality_reason": "Raspunde la grija numarul unu (pretul) inainte ca omul sa "
            "deruleze mai departe.",
            "platform": "all",
            "industry": "",
            "source": "date de proba",
            "observed_at": seen,
        },
        {
            "title": "Greseala pe care o fac toti",
            "hook": "«3 greseli care te costa la programare» - lista numerotata pe ecran.",
            "visual_format": "Carusel 4:5, 5 cadre, text mare, o idee pe cadru",
            "virality_reason": "Bucla deschisa: fiecare cadru promite urmatoarea greseala; "
            "se salveaza si se trimite mai departe.",
            "platform": "meta",
            "industry": "cabinet, clinica, stomatologie, servicii cu programare",
            "source": "date de proba",
            "observed_at": seen,
        },
        {
            "title": "Clientul povesteste, nu firma",
            "hook": "Un client real: «Am amanat doi ani. Uite ce s-a schimbat dupa.»",
            "visual_format": "Testimonial 9:16, 20 s, fara muzica, subtitrari arse",
            "virality_reason": "Mizele unui om ca privitorul - costul amanarii, spus de cineva "
            "care l-a platit.",
            "platform": "all",
            "industry": "",
            "source": "date de proba",
            "observed_at": seen,
        },
        {
            "title": "Comanda azi, ajunge maine",
            "hook": "Coletul deschis in fata camerei, cu data livrarii scrisa pe ecran.",
            "visual_format": "Unboxing 9:16, 10-15 s, sunet real al ambalajului",
            "virality_reason": "Urgenta adevarata, verificabila (data livrarii), nu un "
            "«doar azi» fara motiv.",
            "platform": "tiktok",
            "industry": "magazin online, ecommerce, haine, cosmetice",
            "source": "date de proba",
            "observed_at": seen,
        },
    ]


def save(trends: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps({"trends": trends}, ensure_ascii=False, indent=2), "utf-8")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


def ingest_url(api_url: str) -> str:
    """Adresa rutei; refuza http in afara de localhost (cheia ar pleca in clar).

    Raises:
        ValueError: adresa nu e http(s) sau e http pe un host public.
    """
    parts = urlsplit(api_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("API_URL trebuie să fie o adresă http(s)://")
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        raise ValueError("API_URL trebuie să fie https:// - cheia pleacă în antet")
    return api_url.strip().rstrip("/") + INGEST_PATH


def post(url: str, secret: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Trimite trendurile; intoarce raspunsul serverului (cate create, actualizate, sterse).

    Raises:
        urllib.error.URLError: serverul nu raspunde sau refuza (HTTPError e o subclasa).
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Cron-Secret": secret},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return body


def main() -> int:
    api_url = os.getenv("API_URL", "")
    secret = os.getenv("CRON_SECRET_KEY", "")
    if not api_url or not secret:
        print("Lipsesc API_URL sau CRON_SECRET_KEY.", file=sys.stderr)
        return 2
    try:
        url = ingest_url(api_url)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    today = datetime.now(tz=UTC).date()
    token = os.getenv("META_AD_LIBRARY_TOKEN", "")
    if token:
        try:
            trends = meta_trends(token, search_terms(), today)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            print(f"Meta Ad Library a refuzat ({exc.code}): {detail}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Meta Ad Library nu răspunde: {exc}", file=sys.stderr)
            return 1
        if not trends:
            print("Meta n-a dat nicio reclamă dovedită pe industriile căutate.", file=sys.stderr)
            return 1
    else:
        print("Fără META_AD_LIBRARY_TOKEN: trimit datele de probă.")
        trends = sample_trends(today)
    path = Path(os.getenv("TRENDS_FILE", "trends.json"))
    save(trends, path)
    payload = load(path)
    try:
        result = post(url, secret, payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"Serverul a refuzat trendurile ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Serverul nu răspunde: {exc}", file=sys.stderr)
        return 1
    print(
        f"Trimise {len(payload['trends'])} trenduri: {result.get('created', 0)} noi, "
        f"{result.get('updated', 0)} actualizate, {result.get('expired_deleted', 0)} vechi "
        f"șterse (vectori: {result.get('embedding_model', '?')})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
