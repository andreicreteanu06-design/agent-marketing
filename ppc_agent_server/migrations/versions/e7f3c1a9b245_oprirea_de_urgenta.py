"""oprirea de urgenta

Revision ID: e7f3c1a9b245
Revises: d5e2b9a0c317
Create Date: 2026-10-02 18:00:00.000000

Jurnalul opririlor de urgenta date de un admin din chatul consiliului: cat e activa
una (fara ``resumed_at``), platforma nu cheltuie nimic nou.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'e7f3c1a9b245'
down_revision: Union[str, Sequence[str], None] = 'd5e2b9a0c317'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('emergencystop',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stopped_at', sa.DateTime(), nullable=False),
    sa.Column('stopped_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('resumed_at', sa.DateTime(), nullable=True),
    sa.Column('resumed_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('emergencystop')
