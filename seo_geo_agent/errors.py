"""Tipuri de exceptii pentru seo_geo_agent.

Ierarhie mica, deliberat separata de ``ppc_agent.errors`` (agent separat, nu
un modul al ``ppc_agent`` — vezi ``__init__.py``). Vezi ``app.py`` pentru
maparea la coduri HTTP.
"""

from __future__ import annotations


class SeoGeoAgentError(Exception):
    """Clasa de baza pentru toate erorile acestui agent."""


class SetupRequiredError(SeoGeoAgentError):
    """Ollama nu raspunde, are timeout, sau modelul cerut nu e descarcat.

    Distincta de :class:`AnalysisError`: aici problema e configurarea/mediul,
    nu raspunsul modelului.
    """


class AnalysisError(SeoGeoAgentError):
    """Ollama a raspuns, dar continutul nu e JSON valid conform ``AnalysisResponse``.

    Ridicata si dupa epuizarea retry-urilor din :mod:`seo_geo_agent.engine`.
    """
