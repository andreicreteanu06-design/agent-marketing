"""Fixtures partajate pentru suita de teste."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Directorul cu date de test locale (fara apeluri de retea)."""
    return Path(__file__).parent / "fixtures"
