"""add players.is_verified (verified-pro badge)

Revision ID: b9e3f7a2d1c4
Revises: a6d2e8f1c3b7
Create Date: 2026-10-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b9e3f7a2d1c4'
down_revision = 'a6d2e8f1c3b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('players', sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('players', 'is_verified')
