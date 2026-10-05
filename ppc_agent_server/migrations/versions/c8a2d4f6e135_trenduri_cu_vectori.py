"""trenduri cu vectori

Revision ID: c8a2d4f6e135
Revises: b5e7f9a1c324
Create Date: 2026-10-06 09:00:00.000000

trends_db primeste si trendurile automatizarii saptamanale (``POST /api/v1/trends/ingest``):
fara agentie (``tenant_id`` gol = pentru toti), cu titlul, hook-ul, formatul vizual si
motivul viralitatii, plus vectorul (embedding) si modelul care l-a dat. Evaluarile CCO
pastreaza conceptul (hook-ul principal), ca un concept care a esuat sa fie recunoscut.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c8a2d4f6e135'
down_revision: Union[str, Sequence[str], None] = 'b5e7f9a1c324'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEXT = ('title', 'hook', 'visual_format', 'virality_reason', 'embedding_model')


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('creativetrend') as batch:
        batch.alter_column('tenant_id', existing_type=sa.Integer(), nullable=True)
        for name in _TEXT:
            batch.add_column(
                sa.Column(
                    name, sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''
                )
            )
        batch.add_column(sa.Column('embedding', sa.JSON(), nullable=True))
    op.add_column(
        'creativeevaluation',
        sa.Column(
            'concept', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('creativeevaluation') as batch:
        batch.drop_column('concept')
    op.execute('DELETE FROM creativetrend WHERE tenant_id IS NULL')
    with op.batch_alter_table('creativetrend') as batch:
        batch.drop_column('embedding')
        for name in reversed(_TEXT):
            batch.drop_column(name)
        batch.alter_column('tenant_id', existing_type=sa.Integer(), nullable=False)
