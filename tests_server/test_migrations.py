"""Migratiile Alembic, aplicate pe o baza goala, trebuie sa dea exact modelele.

Restul testelor construiesc schema cu ``create_all`` direct din modele, deci nu
vad o migratie care a uitat ceva. Testul asta o vede: ruleaza ``alembic upgrade
head`` pe un SQLite nou, apoi ``alembic check``, care pica daca modelele cer o
schimbare pe care nicio migratie n-a facut-o.

Ruleaza Alembic in proces separat: ``env.py`` citeste ``DATABASE_URL`` prin
setarile serverului, care sunt tinute in cache per proces.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _alembic(*args: str, database: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ROOT / "alembic.ini"), *args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_migratiile_pe_o_baza_goala_dau_exact_modelele(tmp_path: Path) -> None:
    database = tmp_path / "migrat.db"

    upgrade = _alembic("upgrade", "head", database=database)
    assert upgrade.returncode == 0, upgrade.stderr

    check = _alembic("check", database=database)
    assert check.returncode == 0, check.stderr
