"""Expunerea motorului hibrid PPC+SEO ca server MCP (Model Context Protocol).

Acelasi motor pe care il foloseste site-ul, oferit si agentilor externi (Claude
Desktop, Cursor, orice client MCP). Nu se dubleaza nicio logica: uneltele de
aici cheama exact functiile din ``ppc_agent/search_data/insights.py`` si
``ppc_agent_server/hybrid_queries.py`` pe care le cheama si routerul HTTP.

Trei principii, tinute strict:

1. **Auto-descriptive si tipizate** - schema fiecarei unelte se genereaza din
   adnotarile de tip Python, nu se scrie de mana. O schema scrisa separat de
   functie se desincronizeaza de ea la prima modificare.
2. **Executie fara stare** - o unealta nu tine nimic intre apeluri; contextul
   (ce client e) vine din conexiunea autentificata, nu dintr-un camp global.
3. **Separarea citirii de scriere** - uneltele care citesc raspund direct;
   singura unealta care "scrie" NU aplica nimic, ci creeaza o propunere in
   asteptare. Vezi ``server.py``.
"""

from __future__ import annotations
