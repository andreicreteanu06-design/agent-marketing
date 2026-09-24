"""coloana op incape CREATE_CAMPAIGN pe SQLite

Revision ID: cf2dc48ffe86
Revises: 9ec485fd0efd
Create Date: 2026-09-24 13:17:01.494518

Completeaza a53455d095d5: acolo ``CREATE_CAMPAIGN`` a intrat in tipul ENUM
nativ din PostgreSQL, dar pe SQLite enum-ul e un ``VARCHAR`` cat cea mai lunga
valoare de la creare - ``VARCHAR(6)``, iar ``CREATE_CAMPAIGN`` are 15 caractere.
SQLite nu verifica lungimea, deci nimic nu pica la rulare; schema ramasa in urma
modelelor facea insa ca fiecare ``alembic revision --autogenerate`` sa propuna
din nou aceeasi modificare, iar ``alembic check`` sa pice.

Pe PostgreSQL nu e nimic de facut: tipul nativ a fost extins in a53455d095d5.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf2dc48ffe86'
down_revision: Union[str, Sequence[str], None] = '9ec485fd0efd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_OP = sa.Enum('CREATE', 'UPDATE', 'PAUSE', name='changeop')
_NEW_OP = sa.Enum('CREATE', 'UPDATE', 'PAUSE', 'CREATE_CAMPAIGN', name='changeop')


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name != "sqlite":
        return
    # SQLite nu stie ALTER COLUMN: modul batch recreeaza tabela si copiaza randurile.
    with op.batch_alter_table('proposedchange') as batch_op:
        batch_op.alter_column(
            'op', existing_type=_OLD_OP, type_=_NEW_OP, existing_nullable=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table('proposedchange') as batch_op:
        batch_op.alter_column(
            'op', existing_type=_NEW_OP, type_=_OLD_OP, existing_nullable=False
        )
