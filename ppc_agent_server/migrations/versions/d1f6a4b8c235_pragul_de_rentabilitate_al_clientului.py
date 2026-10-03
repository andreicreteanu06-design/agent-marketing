"""pragul de rentabilitate al clientului

Revision ID: d1f6a4b8c235
Revises: c9e5f3a7b124
Create Date: 2026-10-03 20:00:00.000000

``clientaccount.min_roas``: ROAS-ul de la care contul castiga bani (la un magazin
1 / marja). Gol = implicitul obiectivului - vezi ``campaign_objective.break_even_roas``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1f6a4b8c235'
down_revision: Union[str, Sequence[str], None] = 'c9e5f3a7b124'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'clientaccount',
        sa.Column('min_roas', sa.Numeric(precision=10, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clientaccount', 'min_roas')
