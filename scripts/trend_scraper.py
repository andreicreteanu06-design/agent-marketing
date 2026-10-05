"""Trendurile saptamanii -> ``trends.json`` -> ``POST /api/v1/trends/ingest``.

Il ruleaza GitHub Actions in fiecare luni (``.github/workflows/trend_ingestion.yml``).
Python pur, doar biblioteca standard - pe runner nu se instaleaza nimic. Deocamdata
trendurile sunt date de proba (:func:`collect_trends`); un scraper real le inlocuieste
acolo, cu aceeasi forma (``TrendPayload`` din ``services/creative_context.py``).

Variabile de mediu:
    API_URL           adresa publica a API-ului (ex. https://api.exemplu.ro), HTTPS -
                      cheia pleaca in antet; http doar pentru localhost.
    CRON_SECRET_KEY   aceeasi valoare ca in .env-ul serverului (antetul X-Cron-Secret).
    TRENDS_FILE       optional, unde se scrie fisierul intermediar (implicit trends.json).

Coduri de iesire: 0 trimis, 1 serverul a refuzat sau nu raspunde, 2 lipsesc variabile.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

INGEST_PATH = "/api/v1/trends/ingest"
TIMEOUT_SECONDS = 60
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def collect_trends(today: date) -> list[dict[str, Any]]:
    """Trendurile saptamanii - DATE DE PROBA, pana la scraper-ul real.

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
    path = Path(os.getenv("TRENDS_FILE", "trends.json"))
    save(collect_trends(datetime.now(tz=UTC).date()), path)
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
