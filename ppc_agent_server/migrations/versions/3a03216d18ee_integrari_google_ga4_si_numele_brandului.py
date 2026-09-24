"""integrari google ga4 si numele brandului

Revision ID: 3a03216d18ee
Revises: cf2dc48ffe86
Create Date: 2026-09-24 20:30:27.338669

Conectarea Google Analytics 4 (token criptat + proprietatea aleasa) si numele
brandului din Setari. Search Console avea deja coloanele (0a4284e2ffdc).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '3a03216d18ee'
down_revision: Union[str, Sequence[str], None] = 'cf2dc48ffe86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default explicit (aceeasi ajustare ca la 0a4284e2ffdc): o coloana
    # NOT NULL fara valoare implicita nu se poate adauga pe o tabela cu randuri.
    for column in ('ga4_refresh_token_enc', 'ga4_property_id', 'brand_name'):
        op.add_column(
            'clientaccount',
            sa.Column(
                column,
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default='',
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clientaccount', 'brand_name')
    op.drop_column('clientaccount', 'ga4_property_id')
    op.drop_column('clientaccount', 'ga4_refresh_token_enc')
