"""auditul tehnic seo geo pentru tehnician

Revision ID: b7e41c9d2a53
Revises: 60c8c372d75c
Create Date: 2026-09-29 12:00:00.000000

Rezumatele auditurilor tehnice SEO/GEO ale site-ului fiecarui client, scrise noaptea
de ``run_site_audit_job`` (motorul de audit al agentului SEO/GEO) si citite de
Tehnician: scorurile, problemele pe severitate si cele mai grave, cu reparatia.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b7e41c9d2a53'
down_revision: Union[str, Sequence[str], None] = '60c8c372d75c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('siteauditsnapshot',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_account_id', sa.Integer(), nullable=False),
    sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('audited_at', sa.DateTime(), nullable=False),
    sa.Column('pages_crawled', sa.Integer(), nullable=False),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('seo_score', sa.Integer(), nullable=True),
    sa.Column('geo_score', sa.Integer(), nullable=True),
    sa.Column('critical_issues', sa.Integer(), nullable=False),
    sa.Column('warning_issues', sa.Integer(), nullable=False),
    sa.Column('info_issues', sa.Integer(), nullable=False),
    sa.Column('top_issues', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['client_account_id'], ['clientaccount.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_siteauditsnapshot_audited_at'), 'siteauditsnapshot', ['audited_at'], unique=False)
    op.create_index(op.f('ix_siteauditsnapshot_client_account_id'), 'siteauditsnapshot', ['client_account_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_siteauditsnapshot_client_account_id'), table_name='siteauditsnapshot')
    op.drop_index(op.f('ix_siteauditsnapshot_audited_at'), table_name='siteauditsnapshot')
    op.drop_table('siteauditsnapshot')
