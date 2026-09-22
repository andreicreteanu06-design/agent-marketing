"""Surse de date pentru cautarea ORGANICA (SEO), distincte de ``providers/``.

``ppc_agent/providers/`` sunt platformele de RECLAME (Google Ads, Meta, TikTok):
de acolo vin cheltuiala si conversiile platite. Pachetul asta aduce cealalta
jumatate - ce se intampla in cautarea organica - din surse gratuite si
oficiale, fara niciun vendor de date SEO:

- ``search_console`` — Google Search Console: pozitiile, afisarile si
  click-urile REALE ale site-ului propriu. Nu estimari, nu scraping.
- ``keyword_planner`` — Google Ads API: volume de cautare si termenii reali
  care au declansat reclame (cu conversii). Gratuit, acelasi cont pe care
  clientul il are deja conectat.
- ``common_crawl`` — graful public de linkuri: autoritate de domeniu pentru
  orice site, inclusiv al concurentilor.
- ``insights`` — analizele care ies din IMBINAREA acestor date cu cele de
  reclame. Aici sta valoarea pe care un tool de SEO pur nu o poate produce:
  el nu vede cat platesti si ce converteste.

Toate clientele urmeaza tiparul din ``providers/live/``: ``httpx`` simplu (fara
SDK-uri grele), ``transport`` injectabil pentru teste fara retea, erori
traduse in ``SetupRequiredError``/``ProviderError``.
"""

from __future__ import annotations
