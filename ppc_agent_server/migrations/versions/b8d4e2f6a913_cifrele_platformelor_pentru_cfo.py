"""cifrele platformelor pentru CFO

Revision ID: b8d4e2f6a913
Revises: e7f3c1a9b245
Create Date: 2026-10-03 12:00:00.000000

Ultima citire, pe 30 de zile, a seturilor de reclame/campaniilor fiecarui client - aceeasi
din care Kelly si Thompson muta bugetele. O citeste CFO-ul consiliului.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b8d4e2f6a913'
down_revision: Union[str, Sequence[str], None] = 'e7f3c1a9b245'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('platformarmsnapshot',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_account_id', sa.Integer(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('arm_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('clicks', sa.Integer(), nullable=False),
    sa.Column('conversions', sa.Integer(), nullable=False),
    sa.Column('cost', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('revenue', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['client_account_id'], ['clientaccount.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_platformarmsnapshot_client_account_id'), 'platformarmsnapshot', ['client_account_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_platformarmsnapshot_client_account_id'), table_name='platformarmsnapshot')
    op.drop_table('platformarmsnapshot')
