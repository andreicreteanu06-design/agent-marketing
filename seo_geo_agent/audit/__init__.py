"""Motorul de audit determinist al ``seo_geo_agent``.

Portare fidela a arhitecturii din ``every-app/open-seo`` (Cloudflare Workers +
TypeScript) in Python/asyncio, cu ACELEASI id-uri de probleme, aceleasi
severitati si aceleasi praguri numerice — vezi ``issues.py`` si
``page_reporters.py``. Textele (titlu/explicatie/cum-se-repara) sunt in romana,
ca restul produsului; identificatorii raman in engleza, kebab-case, identici cu
originalul.

Ideea de baza, preluata ca atare: un audit NU e o parere a unui model de limbaj.
E un crawl real al site-ului, din care functii pure calculeaza probleme
verificabile, fiecare cu dovada ei (URL-ul afectat + valorile masurate). LLM-ul
(``seo_geo_agent/llm.py``) ramane un strat optional PESTE datele masurate, nu
sursa lor.

Fluxul, in ordine (fiecare pas are modulul lui):

1. ``url_policy``  — validarea si normalizarea URL-ului de start (anti-SSRF).
2. ``robots``      — robots.txt: ce are voie crawler-ul, ce sitemap-uri exista.
3. ``discovery``   — sitemap.xml (+ index-uri imbricate) => URL-uri seed.
4. ``crawler``     — descarcarea paginilor, clasificarea raspunsului.
5. ``page_analyzer`` — extragerea datelor SEO din HTML (tokenizer, nu DOM).
6. ``page_reporters`` — verificari pure per pagina.
7. ``multipage``   — verificari intre pagini (duplicate, linkuri rupte, orfane).
8. ``geo_reporters`` — verificari GEO (citabilitate in motoare generative).
9. ``scoring``     — scorurile SEO/GEO, derivate DIN probleme, nu invers.
10. ``service``    — orchestrarea; ``store`` — registrul de audituri in memorie.
"""

from __future__ import annotations
