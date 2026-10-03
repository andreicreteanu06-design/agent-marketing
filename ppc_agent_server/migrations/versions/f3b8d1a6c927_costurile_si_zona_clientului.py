"""costurile si zona clientului

Revision ID: f3b8d1a6c927
Revises: e7a2c5d9b146
Create Date: 2026-10-04 10:00:00.000000

Inaintea primei campanii, consiliul cere clientului costurile (din ele: CAC-ul maxim si
pragul de rentabilitate) si zona in care merg reclamele (adresa si raza). Toate pe
``clientaccount``, optionale - un client vechi le completeaza la urmatoarea lansare.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'f3b8d1a6c927'
down_revision: Union[str, Sequence[str], None] = 'e7a2c5d9b146'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = (
    'average_order_value',
    'product_cost',
    'shipping_cost',
    'payment_fee_pct',
    'return_rate_pct',
    'customer_profit',
    'close_rate_pct',
    'max_travel_km',
    'target_radius_km',
)
_TEXT = (
    'service_area',
    'business_address',
    'business_kind',
    'location_label',
    'place_size',
    'intake_step',
)
_COORDINATES = ('location_lat', 'location_lng')


def upgrade() -> None:
    """Upgrade schema."""
    for name in _MONEY:
        op.add_column(
            'clientaccount', sa.Column(name, sa.Numeric(precision=10, scale=2), nullable=True)
        )
    for name in _COORDINATES:
        op.add_column(
            'clientaccount', sa.Column(name, sa.Numeric(precision=9, scale=6), nullable=True)
        )
    for name in _TEXT:
        op.add_column(
            'clientaccount',
            sa.Column(name, sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        )
    op.add_column(
        'clientaccount', sa.Column('economics_confirmed_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('clientaccount') as batch:
        batch.drop_column('economics_confirmed_at')
        for name in (*_TEXT, *_COORDINATES, *_MONEY):
            batch.drop_column(name)
