"""monitorul vede reclamele din Meta

Revision ID: c9e5f3a7b124
Revises: b8d4e2f6a913
Create Date: 2026-10-03 16:00:00.000000

Monitorul de oboseala primeste si anunturile fara nicio vanzare, citite din Meta:

- ``adperformancerecord.platform_conversions``/``platform_revenue``: ce raporteaza
  platforma, langa conversiile din webhook (``conversions``/``revenue``, neatinse).
- ``PAUSED`` in ``adlifecyclestatus``: anuntul nu ruleaza in platforma. Pe SQLite
  enum-ul e un ``VARCHAR(10)`` si ``PAUSED`` incape; pe PostgreSQL tipul nativ se
  extinde, ca la ``BLOCKED`` (60c8c372d75c).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9e5f3a7b124'
down_revision: Union[str, Sequence[str], None] = 'b8d4e2f6a913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default: o coloana NOT NULL nu se adauga altfel pe o tabela cu randuri.
    op.add_column(
        'adperformancerecord',
        sa.Column('platform_conversions', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'adperformancerecord',
        sa.Column(
            'platform_revenue',
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default='0',
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        # ADD VALUE nu poate rula intr-o tranzactie pe Postgres < 12. Valoarea e
        # NUMELE membrului enum (asa il persista SQLAlchemy), nu valoarea lui.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE adlifecyclestatus ADD VALUE IF NOT EXISTS 'PAUSED'")


def downgrade() -> None:
    """Downgrade schema.

    ``PAUSED`` ramane in tipul Postgres (vezi 60c8c372d75c); o valoare nefolosita e
    inofensiva.
    """
    op.drop_column('adperformancerecord', 'platform_revenue')
    op.drop_column('adperformancerecord', 'platform_conversions')
