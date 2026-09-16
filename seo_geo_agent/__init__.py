"""seo_geo_agent — agent AI separat pentru analiza SEO (Search Engine Optimization)
si GEO (Generative Engine Optimization) a unui domeniu.

Pachet de sine statator, nu un modul al ``ppc_agent``: propriul FastAPI app
(``seo_geo_agent.app:app``, alt port), propriile dependinte
(``requirements-seo-geo.txt``, fara SQLModel/Alembic/Redis — nu are nevoie de
baza de date proprie) si propriul client LLM. Singura suprafata comuna cu
``ppc_agent_server`` e ``JWT_SECRET_KEY`` din acelasi ``.env`` — clientii
autentificati pe site (POST /api/v1/login din ppc_agent_server) folosesc
acelasi token si aici (vezi ``seo_geo_agent/auth.py``), fara un al doilea login.
"""

from __future__ import annotations

__version__ = "0.1.0"
