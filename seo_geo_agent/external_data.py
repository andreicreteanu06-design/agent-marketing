"""Client-uri opționale pentru date externe GRATUITE, din ``public-apis/public-apis``
(plus Hugging Face, sugerat separat).

Cele 4 surse alese (vezi raportul din conversație pentru criteriile de selecție):

- :func:`fetch_page_content` — Microlink.io: extrage titlu/descriere/text al unei
  pagini, fără cont, fără cheie. Hrănește motorul GEO cu conținut real al site-ului
  clientului, nu doar cu ce descrie el în ``client_reports``.
- :func:`fetch_pagespeed_insights` — Google PageSpeed Insights v5: scoruri Core
  Web Vitals reale. Funcționează fără cheie (cotă mică, ok pentru un singur
  domeniu per cerere); cheia e opțională, vezi ``SEOGEO_PAGESPEED_API_KEY``.
- :func:`fetch_text_quality` — LanguageTool: verificare gramaticală/de claritate,
  fără cont. Un text cu multe erori sau propoziții greoaie e un semnal negativ
  atât pentru SEO cât și pentru citabilitate GEO (modelele AI preferă text clar).
- :func:`fetch_semantic_embedding` — Hugging Face Inference API (model
  ``sentence-transformers/all-MiniLM-L6-v2``): un vector de embedding pentru un
  text. Util pentru similaritate semantică (ex. cât de aproape e conținutul
  clientului de publicul țintă/subiectul cerut) — un semnal GEO pe care simpla
  potrivire de cuvinte-cheie nu-l poate da. Spre deosebire de celelalte 3, HF
  cere un token gratuit (``SEOGEO_HUGGINGFACE_API_KEY``); fără el, funcția nu
  face niciun apel de rețea și întoarce direct ``None``.

CRITIC: astea sunt API-uri publice gratuite - vor avea rate-limit-uri și
downtime. Fiecare funcție prinde orice eroare (timeout, conexiune, HTTP 4xx/5xx,
JSON invalid, formă neașteptată a răspunsului) și întoarce ``None`` - NU trebuie
niciodată să pice cererea FastAPI către ``/analyze``. Nu sunt încă folosite în
``engine.py``/prompt-ul LLM-ului (integrarea rămâne un pas separat, deliberat).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("seo_geo_agent.external_data")

_DEFAULT_TIMEOUT = 10.0
_HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


async def fetch_page_content(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """Titlu, descriere și text al paginii ``url``, via Microlink.io (fără cheie).

    Util pentru GEO: modelul de analiză poate compara ce spune clientul în
    ``client_reports`` cu ce e de fapt pe pagină. Întoarce ``None`` la orice
    eșec (Microlink e gratuit fără cont, deci rate-limitat).
    """
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.get(
                "https://api.microlink.io/",
                params={"url": url, "meta": "true"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_page_content a eșuat pentru %s: %s", url, exc)
        return None

    if payload.get("status") != "success":
        logger.warning("fetch_page_content: Microlink a răspuns fără succes pentru %s", url)
        return None

    data = payload.get("data", {})
    return {
        "title": data.get("title"),
        "description": data.get("description"),
        "publisher": data.get("publisher"),
        "lang": data.get("lang"),
    }


def _rounded(audits: dict[str, Any], key: str, *, digits: int = 0) -> float | None:
    """``numericValue`` al unui audit Lighthouse, rotunjit; ``None`` cand lipseste."""
    value = audits.get(key, {}).get("numericValue")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(float(value), digits) if digits else float(round(value))


def _field_data(payload: dict[str, Any]) -> dict[str, float | None]:
    """Datele de teren CrUX (utilizatori reali, percentila 75), cand Google le are.

    ``loadingExperience`` lipseste pentru site-urile cu trafic mic. CLS vine din CrUX
    inmultit cu 100 (``10`` = ``0.10``).
    """
    metrics = (payload.get("loadingExperience") or {}).get("metrics") or {}

    def _p75(key: str) -> float | None:
        value = (metrics.get(key) or {}).get("percentile")
        return float(value) if isinstance(value, int | float) else None

    cls = _p75("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    return {
        "field_lcp_ms": _p75("LARGEST_CONTENTFUL_PAINT_MS"),
        "field_cls": round(cls / 100, 3) if cls is not None else None,
        "field_inp_ms": _p75("INTERACTION_TO_NEXT_PAINT"),
    }


async def fetch_pagespeed_insights(
    url: str,
    *,
    api_key: str = "",
    strategy: str = "mobile",
    timeout: float = _DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """Scoruri Core Web Vitals pentru ``url``, via Google PageSpeed Insights v5.

    ``api_key`` e opțional - fără el, Google permite un volum mic de cereri
    (suficient pentru analize ocazionale, unul-câte-unul). Cu
    ``SEOGEO_PAGESPEED_API_KEY`` setat, cota crește. Întoarce ``None`` la orice
    eșec (timeout, 429, domeniu inexistent, etc.).

    Cheile ``largest_contentful_paint``/``cumulative_layout_shift``/
    ``total_blocking_time`` sunt textul afișat de Google ("2,9 s"); ``lcp_ms``,
    ``cls`` și ``tbt_ms`` sunt aceleași metrici ca numere (``None`` când
    lipsesc) - le folosește Tehnicianul serverului PPC pentru praguri; ``field_*`` sunt
    datele de teren CrUX (p75), ``None`` când Google nu le are.
    """
    params: dict[str, str] = {"url": url, "strategy": strategy, "category": "performance"}
    if api_key:
        params["key"] = api_key

    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_pagespeed_insights a eșuat pentru %s: %s", url, exc)
        return None

    try:
        lighthouse = payload["lighthouseResult"]
        categories = lighthouse["categories"]
        audits = lighthouse["audits"]
        return {
            "performance_score": round(categories["performance"]["score"] * 100),
            "largest_contentful_paint": audits.get("largest-contentful-paint", {}).get(
                "displayValue"
            ),
            "cumulative_layout_shift": audits.get("cumulative-layout-shift", {}).get(
                "displayValue"
            ),
            "total_blocking_time": audits.get("total-blocking-time", {}).get("displayValue"),
            # Aceleasi metrici ca numere (``numericValue``), pentru praguri: textul de
            # mai sus e pentru oameni ("2,9 s"), nu pentru comparatii.
            "lcp_ms": _rounded(audits, "largest-contentful-paint"),
            "cls": _rounded(audits, "cumulative-layout-shift", digits=3),
            "tbt_ms": _rounded(audits, "total-blocking-time"),
            **_field_data(payload),
        }
    except (KeyError, TypeError) as exc:
        logger.warning("fetch_pagespeed_insights: răspuns neașteptat pentru %s: %s", url, exc)
        return None


async def fetch_text_quality(
    text: str,
    *,
    language: str = "auto",
    timeout: float = _DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """Numărul și tipurile de probleme de claritate/gramatică din ``text``, via LanguageTool.

    Un text greu de citit sau plin de greșeli e un semnal negativ atât pentru
    SEO cât și pentru citabilitate GEO. Serverul public LanguageTool e gratuit,
    fără cont, dar limitează lungimea textului și numărul de cereri - la orice
    eșec (inclusiv text prea lung) întoarce ``None``.
    """
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.post(
                "https://api.languagetool.org/v2/check",
                data={"text": text, "language": language},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_text_quality a eșuat: %s", exc)
        return None

    matches = payload.get("matches")
    if matches is None:
        logger.warning("fetch_text_quality: răspuns neașteptat de la LanguageTool")
        return None

    categories: dict[str, int] = {}
    for match in matches:
        category = match.get("rule", {}).get("category", {}).get("name", "Altele")
        categories[category] = categories.get(category, 0) + 1

    return {"issue_count": len(matches), "issues_by_category": categories}


def _as_float_matrix(value: Any) -> list[list[float]] | None:
    """Normalizeaza un JSON arbitrar la o matrice de ``float``, sau ``None`` daca nu se potriveste.

    Raspunsul Hugging Face pentru ``feature-extraction`` variaza dupa model: un
    singur text poate produce un vector deja agregat (``list[float]``) sau unul
    per token (``list[list[float]]``) - uneori infasurat intr-un nivel
    suplimentar pentru "batch de 1". Aceasta functie accepta ambele forme plate
    si respinge (``None``) orice altceva, in loc sa ridice o exceptie de tip.
    """
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(x, (int, float)) for x in value):
        return [[float(x) for x in value]]
    if all(isinstance(row, list) for row in value):
        rows: list[list[float]] = []
        for row in value:
            if not all(isinstance(x, (int, float)) for x in row):
                return None
            rows.append([float(x) for x in row])
        return rows
    return None


def _mean_pool(vectors: list[list[float]]) -> list[float]:
    """Media pe coloane a unui set de vectori - reduce embeddings per-token la unul singur."""
    dims = len(vectors[0])
    sums = [0.0] * dims
    for vector in vectors:
        for i, value in enumerate(vector):
            sums[i] += value
    return [total / len(vectors) for total in sums]


async def fetch_semantic_embedding(
    text: str,
    *,
    api_key: str = "",
    model: str = _HF_MODEL,
    timeout: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[float] | None:
    """Vector de embedding pentru ``text``, via Hugging Face Inference API.

    Fara ``api_key`` (``SEOGEO_HUGGINGFACE_API_KEY``), Hugging Face refuza
    cererile anonime pentru majoritatea modelelor - nu are rost sa incercam, deci
    functia intoarce direct ``None``, fara niciun apel de retea. Timeout implicit
    mai mare decat celelalte functii (30s, nu 10s): la primul apel dupa o vreme,
    modelul poate fi "cold" si Inference API il incarca inainte sa raspunda
    (``options.wait_for_model``).
    """
    if not api_key:
        logger.warning(
            "fetch_semantic_embedding: lipseste SEOGEO_HUGGINGFACE_API_KEY, sar peste apel"
        )
        return None

    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"inputs": text, "options": {"wait_for_model": True}},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_semantic_embedding a eșuat pentru modelul %s: %s", model, exc)
        return None

    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], list):
        payload = payload[0]  # unwrap invelisul de "batch de 1" pe care unele modele il adauga

    matrix = _as_float_matrix(payload)
    if matrix is None:
        logger.warning(
            "fetch_semantic_embedding: răspuns neașteptat de la Hugging Face pentru modelul %s",
            model,
        )
        return None

    return _mean_pool(matrix)
