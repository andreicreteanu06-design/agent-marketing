"""Structuri de date tipizate pentru seo_geo_agent: cererea de analiza si
raspunsul strict pe care trebuie sa il produca LLM-ul.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    """Cererea de analiza SEO+GEO pentru un domeniu."""

    domain: str = Field(min_length=1, description="Domeniul analizat, ex. exemplu.ro")
    client_reports: str = Field(
        min_length=1,
        description=(
            "Text brut din rapoarte/unelte ale clientului (Ahrefs, Semrush, "
            "Google Search Console etc.) - sursa principala de date reale pentru "
            "sugestii, nu doar cunostinte generale despre domeniu."
        ),
    )
    target_audience: str | None = Field(
        default=None, description="Descrierea publicului tinta, daca e cunoscuta."
    )


class ActionableSuggestion(BaseModel):
    """O sugestie unica, actionabila - nu un sfat generic.

    ``exact_fix`` trebuie sa fie ceva ce un dezvoltator/marketer poate copia
    direct: cod JSON-LD, textul exact de schimbat, markup HTML precis - nu
    "imbunatateste continutul".
    """

    category: str = Field(description='Ex. "Schema Markup", "Entity Salience", "Continut".')
    current_issue: str = Field(description="Problema concreta gasita, pe baza datelor din cerere.")
    exact_fix: str = Field(
        description="Directiva tehnica exacta - cod, text, sau markup, nu vorbe goale."
    )


class AnalysisResponse(BaseModel):
    """Raspunsul complet al analizei: doua scoruri + doua liste de sugestii."""

    seo_score: int = Field(
        ge=0, le=100, description="Scor SEO clasic (motoare de cautare traditionale)."
    )
    geo_score: int = Field(
        ge=0,
        le=100,
        description="Scor GEO (Generative Engine Optimization - citabilitate in raspunsuri AI).",
    )
    seo_suggestions: list[ActionableSuggestion] = Field(default_factory=list)
    geo_suggestions: list[ActionableSuggestion] = Field(default_factory=list)
