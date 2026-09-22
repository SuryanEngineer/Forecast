"""add is_historical_archive flag to tournaments

Revision ID: c9a1f4e7d2b5
Revises: b8e4d2f61c7a
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9a1f4e7d2b5'
down_revision = 'b8e4d2f61c7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tournaments',
        sa.Column('is_historical_archive', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('tournaments', 'is_historical_archive')
