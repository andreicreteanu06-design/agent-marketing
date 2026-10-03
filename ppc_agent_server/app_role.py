"""Rolul limitat cu care API-ul si worker-ul se conecteaza la Postgres.

Proprietarul bazei (``ppc_agent``, superuser-ul imaginii postgres) ruleaza doar
migratiile, din containerul ``migrate``, o data per pornire. API-ul si worker-ul -
procesele care primesc cereri din internet - folosesc ``ppc_app``: citesc si scriu
randuri, atat. Nu pot crea, sterge sau modifica tabele, nu pot citi fisiere sau
rula comenzi pe server (``pg_read_file``, ``COPY ... PROGRAM``), nu pot crea alti
utilizatori. O injectie SQL, daca ar aparea vreodata, ar ramane in tabele.

Rulat de ``migrate`` dupa ``alembic upgrade head`` (docker-compose.yml): creeaza
rolul daca lipseste, ii pune parola din ``POSTGRES_APP_PASSWORD`` si da drepturile
pe toate tabelele, inclusiv pe cele aduse de migrarea de acum.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

APP_ROLE = "ppc_app"


def ensure_app_role(database_url: str, password: str, role: str = APP_ROLE) -> None:
    """Idempotent: rulat la fiecare pornire, aduce rolul la exact drepturile de mai jos."""
    conninfo = make_url(database_url).set(drivername="postgresql")
    name = sql.Identifier(role)
    with psycopg.connect(conninfo.render_as_string(hide_password=False), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is None:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(name))
        statements = [
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
                " NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(name, sql.Literal(password)),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(conn.info.dbname), name
            ),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(name),
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(name),
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                name
            ),
            # Versiunea schemei o scrie doar migrate.
            sql.SQL("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {}").format(name),
        ]
        for statement in statements:
            conn.execute(statement)


def main() -> None:
    password = os.environ.get("POSTGRES_APP_PASSWORD", "")
    if not password:
        raise SystemExit("POSTGRES_APP_PASSWORD lipseste din .env")
    ensure_app_role(os.environ["DATABASE_URL"], password)
    print(f"rolul {APP_ROLE}: doar citire si scriere de randuri")


if __name__ == "__main__":
    main()
