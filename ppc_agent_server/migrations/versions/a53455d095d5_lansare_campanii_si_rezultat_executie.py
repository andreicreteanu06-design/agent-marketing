"""lansare campanii si rezultat executie

Revision ID: a53455d095d5
Revises: 11a01a294285
Create Date: 2026-09-23 12:00:00.000000

Pe langa coloana noua, repara o scapare din 11a01a294285: acolo s-a adaugat
starea ``FAILED`` in Python, dar nu si in tipul ENUM nativ din PostgreSQL.
SQLite nu verifica valorile enum-ului, deci testele n-au vazut nimic; pe
Postgres, prima propunere marcata ``FAILED`` ar fi picat cu
``invalid input value for enum changestatus``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a53455d095d5'
down_revision: Union[str, Sequence[str], None] = '11a01a294285'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('proposedchange', sa.Column('execution_result', sa.JSON(), nullable=True))

    if op.get_bind().dialect.name == "postgresql":
        # ADD VALUE nu poate rula intr-o tranzactie pe Postgres < 12. Valorile
        # sunt NUMELE membrilor enum (asa le persista SQLAlchemy), nu valorile.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE changeop ADD VALUE IF NOT EXISTS 'CREATE_CAMPAIGN'")
            op.execute("ALTER TYPE changestatus ADD VALUE IF NOT EXISTS 'FAILED'")


def downgrade() -> None:
    """Downgrade schema.

    Valorile adaugate in ENUM-urile Postgres raman: Postgres nu poate scoate o
    valoare dintr-un tip fara sa-l recreeze, iar asta ar cere rescrierea
    tuturor randurilor care o folosesc. O valoare in plus, nefolosita, e
    inofensiva.
    """
    op.drop_column('proposedchange', 'execution_result')
