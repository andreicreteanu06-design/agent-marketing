"""Vectorii trendurilor (RAG-ul CCO-ului): embeddings Ollama sau, fara model, lexicali.

- :class:`OllamaEmbedder` - modelul de embeddings de pe server (``OLLAMA_EMBED_MODEL``,
  ex. ``nomic-embed-text``): gaseste si sinonimele ("service auto" ~ "atelier mecanic").
- :class:`HashEmbedder` - fara niciun model: n-grame de 3 litere pe textul normalizat,
  hash-uite in 256 de dimensiuni (feature hashing). Gaseste aceleasi cuvinte si formele
  lor ("service"/"serviceul"), nu si sinonimele. E rezerva cand Ollama nu are model de
  embeddings sau nu raspunde - ingestia nu pica din cauza lui.

Vectorii stau ca JSON langa trend, cu numele modelului: se compara doar vectori din
acelasi model. Cosinusul se calculeaza in Python - sute de trenduri, nu milioane.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from ppc_agent.errors import ProviderError
from ppc_agent.texttools import normalize
from ppc_agent_server.settings import ServerSettings

HASH_MODEL = "hash-trigram-256"
HASH_DIMENSIONS = 256
#: Zecimalele pastrate in DB: destule pentru cosinus, de 3 ori mai putin JSON.
STORED_DIGITS = 5


class Embedder(Protocol):
    """Text -> vector, cu numele modelului (vectorii se compara doar in acelasi model)."""

    @property
    def model(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, STORED_DIGITS) for value in vector]


@dataclass(frozen=True)
class HashEmbedder:
    """Vectori lexicali, fara model: n-grame de litere, hash-uite (feature hashing)."""

    dimensions: int = HASH_DIMENSIONS

    @property
    def model(self) -> str:
        return HASH_MODEL

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in normalize(text).split():
            padded = f" {word} "
            for start in range(len(padded) - 2):
                digest = hashlib.blake2b(padded[start : start + 3].encode(), digest_size=4)
                value = int.from_bytes(digest.digest(), "big")
                # Bitul de semn imparte coliziunile: doua n-grame pe acelasi index se anuleaza.
                vector[value % self.dimensions] += 1.0 if value & 1 << 31 else -1.0
        return _unit(vector)


@dataclass(frozen=True)
class OllamaEmbedder:
    """``POST /api/embed`` pe serverul Ollama, cu un model de embeddings."""

    host: str
    model: str
    timeout: float = 60.0
    transport: httpx.BaseTransport | None = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Raises:
        ProviderError: Ollama nu raspunde sau modelul nu stie embeddings.
        """
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(
                    f"{self.host}/api/embed", json={"model": self.model, "input": list(texts)}
                )
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if len(vectors) != len(texts):
                raise ValueError("alt numar de vectori decat de texte")
            return [_unit([float(value) for value in vector]) for vector in vectors]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"embeddings Ollama ({self.model}) au picat: {exc}") from exc


def embedder_from_settings(settings: ServerSettings) -> Embedder:
    """Modelul de pe server cand e configurat; altfel vectorii lexicali, fara model."""
    if settings.ollama_embed_model and settings.ollama_host:
        return OllamaEmbedder(host=settings.ollama_host, model=settings.ollama_embed_model)
    return HashEmbedder()


def embed_or_fallback(embedder: Embedder, texts: Sequence[str]) -> tuple[str, list[list[float]]]:
    """Vectorii si modelul care i-a dat: la o cadere a lui Ollama, vectorii lexicali."""
    try:
        return embedder.model, embedder.embed(texts)
    except ProviderError:
        fallback = HashEmbedder()
        return fallback.model, fallback.embed(texts)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Similaritatea a doi vectori (deja normati la salvare, dar nu presupunem)."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norms if norms else 0.0
