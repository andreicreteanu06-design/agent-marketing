from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel
from sqlmodel.sql.sqltypes import AutoString

# Importul incarca toate clasele table=True pe SQLModel.metadata — necesar ca
# autogenerate sa le "vada". Fara acest import, target_metadata ar fi gol.
import ppc_agent_server.models  # noqa: F401
from ppc_agent_server.settings import get_server_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL-ul vine din ServerSettings (DATABASE_URL din mediu), nu din alembic.ini —
# o singura sursa de adevar, aceeasi pe care o foloseste si aplicatia FastAPI.
config.set_main_option("sqlalchemy.url", get_server_settings().database_url)

# Metadata SQLModel — sursa pentru 'alembic revision --autogenerate'.
target_metadata = SQLModel.metadata


def render_item(
    type_: str, obj: Any, autogen_context: AutogenContext
) -> str | Literal[False]:
    """Fixul recomandat de SQLModel: fara asta, migratiile autogenerate refera
    ``sqlmodel.sql.sqltypes.AutoString()`` (tipul folosit pentru coloanele ``str``)
    fara sa importe ``sqlmodel`` — crapa la rulare cu ``NameError``."""
    if type_ == "type" and isinstance(obj, AutoString):
        autogen_context.imports.add("import sqlmodel")
        return "sqlmodel.sql.sqltypes.AutoString()"
    return False

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
