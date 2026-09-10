"""Furnizor de crawling ``mock``: HTML realist, deterministic, fara retea.

Comportamentul depinde de sabloane in URL, ca sa poata fi testate ramurile de
eroare din :func:`ppc_agent.ingestion.crawler.crawl`:

- ``timeout``               -> ridica :class:`CrawlTimeoutError`
- ``404`` sau ``inexistent`` -> raspuns cu status 404
- ``spa`` sau ``js``        -> pagina saraca, randata pe client
- orice altceva             -> landing page complet
- origine care contine ``blocat`` -> ``robots.txt`` interzice tot
"""

from __future__ import annotations

from ppc_agent.errors import CrawlTimeoutError
from ppc_agent.providers.base import CrawlerProvider, FetchResult

_LANDING_HTML = """<!doctype html>
<html lang="ro">
<head>
  <title>FacturarePro - Facturare online rapida pentru firme mici</title>
  <meta name="description" content="Emite facturi in 30 de secunde, trimite automat si incaseaza mai repede. Program de facturare pentru PFA si SRL, cu e-Factura inclusa.">
</head>
<body>
  <nav>
    <a href="/">Acasa</a>
    <a href="/functii">Functii</a>
    <a href="/preturi">Preturi</a>
    <a href="/blog">Blog</a>
    <a href="/contact">Contact</a>
  </nav>
  <header class="hero">
    <h1>Facturare online fara batai de cap</h1>
    <p class="subtitle">Emite si trimite facturi in cateva secunde, cu e-Factura si incasare automata prin card.</p>
    <a class="btn" href="/inregistrare">Incepe gratuit</a>
    <a class="btn btn-secondary" href="/demo">Cere o oferta</a>
  </header>
  <section>
    <h2>De ce FacturarePro</h2>
    <h3>e-Factura inclusa</h3>
    <p>Trimitem automat facturile in SPV, fara pasi manuali.</p>
    <h3>Incasare mai rapida</h3>
    <p>Link de plata pe fiecare factura, reminder automat la scadenta.</p>
    <h3>Rapoarte clare</h3>
    <p>Vezi incasarile si TVA-ul de plata in timp real.</p>
  </section>
  <section>
    <h2>Preturi simple</h2>
    <p>De la 29 lei pe luna. Fara costuri ascunse.</p>
    <a class="btn" href="/preturi">Vezi preturile</a>
  </section>
  <footer>
    <a href="/termeni">Termeni</a>
    <a href="/confidentialitate">Confidentialitate</a>
  </footer>
</body>
</html>
"""

_SPA_HTML = """<!doctype html>
<html lang="ro">
<head><title>App</title></head>
<body>
  <div id="root"></div>
  <noscript>Aceasta aplicatie are nevoie de JavaScript.</noscript>
  <script src="/static/bundle.js"></script>
</body>
</html>
"""

_NOT_FOUND_HTML = """<!doctype html>
<html lang="ro"><head><title>404</title></head>
<body><h1>Pagina nu a fost gasita</h1></body></html>
"""


class MockCrawlerProvider(CrawlerProvider):
    """Crawler deterministic pentru dezvoltare si teste."""

    def fetch(self, url: str) -> FetchResult:
        """Returneaza HTML fixat in functie de sabloanele din ``url``."""
        lowered = url.lower()
        if "timeout" in lowered:
            raise CrawlTimeoutError(f"mock: timeout simulat pentru {url}")
        if "404" in lowered or "inexistent" in lowered:
            return FetchResult(url, url, 404, _NOT_FOUND_HTML, ok=False)
        if "spa" in lowered or "/js" in lowered:
            return FetchResult(url, url, 200, _SPA_HTML, ok=True)
        return FetchResult(url, url, 200, _LANDING_HTML, ok=True)

    def robots_txt(self, base_url: str) -> str | None:
        """``robots.txt`` permisiv, sau restrictiv daca originea contine ``blocat``."""
        if "blocat" in base_url.lower():
            return "User-agent: *\nDisallow: /\n"
        return "User-agent: *\nDisallow: /admin/\nAllow: /\n"
