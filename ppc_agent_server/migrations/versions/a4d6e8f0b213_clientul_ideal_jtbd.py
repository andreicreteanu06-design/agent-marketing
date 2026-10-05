"""clientul ideal in jobs to be done

Revision ID: a4d6e8f0b213
Revises: f3b8d1a6c927
Create Date: 2026-10-05 12:00:00.000000

Dupa costuri si zona, interviul din chat intreaba cine e clientul ideal (Jobs to Be Done:
situatia, treburile, grijile, costul schimbarii) si cum arata oferta (pachete, garantie).
Raspunsurile stau intr-o singura coloana JSON, optionala - un client vechi le completeaza
la urmatoarea lansare.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4d6e8f0b213'
down_revision: Union[str, Sequence[str], None] = 'f3b8d1a6c927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clientaccount', sa.Column('avatar_answers', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('clientaccount') as batch:
        batch.drop_column('avatar_answers')
