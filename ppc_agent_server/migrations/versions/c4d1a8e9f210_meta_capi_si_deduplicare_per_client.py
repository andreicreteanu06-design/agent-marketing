"""meta capi si deduplicare per client

Revision ID: c4d1a8e9f210
Revises: b7e41c9d2a53
Create Date: 2026-09-30 14:00:00.000000

Conversiile pleaca si spre Meta Conversions API: pixelul clientului pe
``clientaccount``, starea trimiterii pe ``conversionevent``. Si deduplicarea
devine per client: ``event_id`` era unic GLOBAL, deci comanda Gomag #1001 a
unui client o ascundea pe #1001 a altuia.

``batch_alter_table``: SQLite nu stie ``ALTER`` pe constrangeri - Alembic
reconstruieste tabela; pe Postgres sunt ALTER-uri obisnuite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c4d1a8e9f210'
down_revision: Union[str, Sequence[str], None] = 'b7e41c9d2a53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'clientaccount',
        sa.Column(
            'meta_pixel_id',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default='',
        ),
    )
    with op.batch_alter_table('conversionevent') as batch:
        batch.add_column(sa.Column('meta_capi_sent_at', sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column('meta_capi_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.drop_index('ix_conversionevent_event_id')
        batch.create_index('ix_conversionevent_event_id', ['event_id'], unique=False)
        batch.create_unique_constraint(
            'uq_conversionevent_client_event', ['client_account_id', 'event_id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversionevent') as batch:
        batch.drop_constraint('uq_conversionevent_client_event', type_='unique')
        batch.drop_index('ix_conversionevent_event_id')
        batch.create_index('ix_conversionevent_event_id', ['event_id'], unique=True)
        batch.drop_column('meta_capi_error')
        batch.drop_column('meta_capi_sent_at')
    op.drop_column('clientaccount', 'meta_pixel_id')
