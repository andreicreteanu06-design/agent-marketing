"""Rolul limitat ``ppc_app``, pe un Postgres real.

Ruleaza doar cu ``TEST_POSTGRES_URL`` = superuser-ul unei baze de unica folosinta
(un container ``postgres:16-alpine`` pornit pentru test), niciodata pe baza stivei:

    TEST_POSTGRES_URL=postgresql+psycopg://ppc_agent:parola@localhost:55432/ppc_agent
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
import pytest
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

from ppc_agent_server.app_role import APP_ROLE, ensure_app_role
from ppc_agent_server.auth import create_tenant
from ppc_agent_server.db import init_db
from ppc_agent_server.models import Tenant

OWNER_URL = os.environ.get("TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not OWNER_URL, reason="cere TEST_POSTGRES_URL (Postgres de test)")

_PASSWORD = "parola-rolului-de-test"


@pytest.fixture(scope="module")
def app_url() -> str:
    env = {**os.environ, "DATABASE_URL": OWNER_URL}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    ensure_app_role(OWNER_URL, _PASSWORD)
    ensure_app_role(OWNER_URL, _PASSWORD)  # a doua pornire: nimic nu cade
    url = make_url(OWNER_URL).set(username=APP_ROLE, password=_PASSWORD)
    return url.render_as_string(hide_password=False)


def test_the_api_starts_and_writes_rows_as_the_app_role(app_url: str) -> None:
    engine = create_engine(app_url)
    init_db(engine)  # create_all la pornirea API-ului: tabelele exista, nimic de creat
    with Session(engine) as session:
        tenant, _key = create_tenant(session, "Agentia de test")
        assert session.exec(select(Tenant).where(Tenant.id == tenant.id)).one().name
        session.delete(tenant)
        session.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE intrus (id int)",
        "DROP TABLE tenant",
        "ALTER TABLE tenant ADD COLUMN intrus int",
        "TRUNCATE tenant",
        "SELECT pg_read_file('/etc/passwd')",
        "COPY tenant TO PROGRAM 'id'",
        "UPDATE alembic_version SET version_num = 'intrus'",
        f"ALTER ROLE {APP_ROLE} SUPERUSER",
        "CREATE ROLE intrus LOGIN",
    ],
)
def test_the_app_role_cannot_touch_the_schema_or_the_server(app_url: str, statement: str) -> None:
    conninfo = make_url(app_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(conninfo) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)
