"""cco invata din piata

Revision ID: b5e7f9a1c324
Revises: a4d6e8f0b213
Create Date: 2026-10-05 18:00:00.000000

CCO-ul nu mai judeca in vid: verdictele lui se pastreaza (``creativeevaluation``), PPC-ul
ii trimite inapoi cifrele din piata, iar ce a prezis gresit devine o corectie
(``performancecalibration``) pe care o citeste inainte de urmatoarea evaluare. Plus
``creativetrend`` (trends_db: ce merge acum pe Meta/TikTok), ipoteza publicata de CMO pe
client si vizionarile de 3 secunde pe anunt (hook rate-ul).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b5e7f9a1c324'
down_revision: Union[str, Sequence[str], None] = 'a4d6e8f0b213'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEXT = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'creativeevaluation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_account_id', sa.Integer(), nullable=False),
        sa.Column('asset_sha256', _TEXT(), nullable=False),
        sa.Column('asset_type', _TEXT(), nullable=False),
        sa.Column('purpose', _TEXT(), nullable=False),
        sa.Column('platform', _TEXT(), nullable=False),
        sa.Column('decision', _TEXT(), nullable=False),
        sa.Column('scores', sa.JSON(), nullable=True),
        sa.Column('ad_platform', _TEXT(), nullable=False),
        sa.Column('ad_id', _TEXT(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_account_id'], ['clientaccount.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_creativeevaluation_client_account_id'), 'creativeevaluation',
        ['client_account_id'], unique=False,
    )
    op.create_index(
        op.f('ix_creativeevaluation_asset_sha256'), 'creativeevaluation', ['asset_sha256'],
        unique=False,
    )
    op.create_index(
        op.f('ix_creativeevaluation_ad_id'), 'creativeevaluation', ['ad_id'], unique=False
    )
    op.create_table(
        'performancecalibration',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_account_id', sa.Integer(), nullable=False),
        sa.Column('evaluation_id', sa.Integer(), nullable=False),
        sa.Column('platform', _TEXT(), nullable=False),
        sa.Column('ad_id', _TEXT(), nullable=False),
        sa.Column('score', _TEXT(), nullable=False),
        sa.Column('predicted', sa.Integer(), nullable=False),
        sa.Column('metric', _TEXT(), nullable=False),
        sa.Column('actual', sa.Float(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('direction', _TEXT(), nullable=False),
        sa.Column('lesson', _TEXT(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_account_id'], ['clientaccount.id']),
        sa.ForeignKeyConstraint(['evaluation_id'], ['creativeevaluation.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('evaluation_id', 'ad_id', 'metric'),
    )
    op.create_index(
        op.f('ix_performancecalibration_client_account_id'), 'performancecalibration',
        ['client_account_id'], unique=False,
    )
    op.create_index(
        op.f('ix_performancecalibration_evaluation_id'), 'performancecalibration',
        ['evaluation_id'], unique=False,
    )
    op.create_table(
        'creativetrend',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('platform', _TEXT(), nullable=False),
        sa.Column('industry', _TEXT(), nullable=False),
        sa.Column('insight', _TEXT(), nullable=False),
        sa.Column('source', _TEXT(), nullable=False),
        sa.Column('observed_at', sa.Date(), nullable=False),
        sa.Column('expires_at', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_creativetrend_tenant_id'), 'creativetrend', ['tenant_id'], unique=False
    )
    op.add_column('clientaccount', sa.Column('cmo_hypothesis', sa.JSON(), nullable=True))
    op.add_column(
        'adperformancerecord',
        sa.Column('video_views', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('adperformancerecord') as batch:
        batch.drop_column('video_views')
    with op.batch_alter_table('clientaccount') as batch:
        batch.drop_column('cmo_hypothesis')
    op.drop_index(op.f('ix_creativetrend_tenant_id'), table_name='creativetrend')
    op.drop_table('creativetrend')
    op.drop_index(
        op.f('ix_performancecalibration_evaluation_id'), table_name='performancecalibration'
    )
    op.drop_index(
        op.f('ix_performancecalibration_client_account_id'), table_name='performancecalibration'
    )
    op.drop_table('performancecalibration')
    op.drop_index(op.f('ix_creativeevaluation_ad_id'), table_name='creativeevaluation')
    op.drop_index(op.f('ix_creativeevaluation_asset_sha256'), table_name='creativeevaluation')
    op.drop_index(
        op.f('ix_creativeevaluation_client_account_id'), table_name='creativeevaluation'
    )
    op.drop_table('creativeevaluation')
