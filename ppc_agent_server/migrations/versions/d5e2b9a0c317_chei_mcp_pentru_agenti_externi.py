"""chei mcp pentru agenti externi

Revision ID: d5e2b9a0c317
Revises: c4d1a8e9f210
Create Date: 2026-10-01 18:00:00.000000

Cheile cu care agentii AI externi (ChatGPT, Claude, n8n...) se conecteaza la serverul
MCP pentru un singur client: doar hash-ul, revocabile, separate de token-ul de login.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'd5e2b9a0c317'
down_revision: Union[str, Sequence[str], None] = 'c4d1a8e9f210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mcpaccesskey',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_account_id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('key_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['client_account_id'], ['clientaccount.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mcpaccesskey_client_account_id'), 'mcpaccesskey', ['client_account_id'], unique=False)
    op.create_index(op.f('ix_mcpaccesskey_key_hash'), 'mcpaccesskey', ['key_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_mcpaccesskey_key_hash'), table_name='mcpaccesskey')
    op.drop_index(op.f('ix_mcpaccesskey_client_account_id'), table_name='mcpaccesskey')
    op.drop_table('mcpaccesskey')
