"""conversii spre google, tiktok si chatgpt

Revision ID: e7a2c5d9b146
Revises: d1f6a4b8c235
Create Date: 2026-10-03 21:00:00.000000

Conversiile calificate pleaca si spre Google Ads (import din click-uri), TikTok
(Events API) si OpenAI Ads (Conversions API), ca spre Meta: identificatorii pe
``clientaccount`` (cheia ChatGPT criptata), starea fiecarei trimiteri pe
``conversionevent``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'e7a2c5d9b146'
down_revision: Union[str, Sequence[str], None] = 'd1f6a4b8c235'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_COLUMNS = (
    'google_ads_conversion_action_id',
    'tiktok_pixel_code',
    'chatgpt_pixel_id',
    'chatgpt_conversions_key_enc',
)
_PLATFORMS = ('google_ads', 'tiktok_events', 'chatgpt_events')


def upgrade() -> None:
    """Upgrade schema."""
    for name in _ACCOUNT_COLUMNS:
        op.add_column(
            'clientaccount',
            sa.Column(
                name, sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''
            ),
        )
    for platform in _PLATFORMS:
        op.add_column(
            'conversionevent', sa.Column(f'{platform}_sent_at', sa.DateTime(), nullable=True)
        )
        op.add_column(
            'conversionevent',
            sa.Column(f'{platform}_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversionevent') as batch:
        for platform in reversed(_PLATFORMS):
            batch.drop_column(f'{platform}_error')
            batch.drop_column(f'{platform}_sent_at')
    with op.batch_alter_table('clientaccount') as batch:
        for name in reversed(_ACCOUNT_COLUMNS):
            batch.drop_column(name)
