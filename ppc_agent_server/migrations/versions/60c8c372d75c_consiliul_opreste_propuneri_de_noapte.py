"""consiliul opreste propuneri de noapte

Revision ID: 60c8c372d75c
Revises: 04fae0115fe8
Create Date: 2026-09-27 13:00:00.000000

Puntea dintre memoria consiliului si jobul PPC de noapte (services/council_guard.py):

- ``memorystream.code``: decizia, pentru masini - codul veto-ului Tehnicianului sau
  felul ideii taiate de CFO. Jobul de noapte il citeste; randurile vechi raman
  ``NULL`` (doar pentru oameni).
- ``BLOCKED`` in ``changestatus``: propunerile oprite de consiliu. Pe SQLite enum-ul e
  un ``VARCHAR(8)`` si ``BLOCKED`` incape; pe PostgreSQL tipul nativ se extinde, ca
  la ``FAILED`` (a53455d095d5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '60c8c372d75c'
down_revision: Union[str, Sequence[str], None] = '04fae0115fe8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('memorystream', sa.Column('code', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    if op.get_bind().dialect.name == "postgresql":
        # ADD VALUE nu poate rula intr-o tranzactie pe Postgres < 12. Valoarea e
        # NUMELE membrului enum (asa il persista SQLAlchemy), nu valoarea lui.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE changestatus ADD VALUE IF NOT EXISTS 'BLOCKED'")


def downgrade() -> None:
    """Downgrade schema.

    ``BLOCKED`` ramane in tipul Postgres (vezi a53455d095d5: o valoare nu se poate
    scoate fara recrearea tipului); o valoare nefolosita e inofensiva.
    """
    op.drop_column('memorystream', 'code')
