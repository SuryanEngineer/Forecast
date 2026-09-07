"""add player power_rating

Revision ID: b7c1a4f92e3d
Revises: f544eefd1096
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b7c1a4f92e3d'
down_revision = 'f544eefd1096'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default='65' so existing rows (created before this column
    # existed) backfill to a neutral "solid journeyman" rating instead of
    # failing the NOT NULL constraint -- see app/models/player.py's
    # power_rating comment for why 65 was picked. New rows going forward
    # get their real rating from whatever an admin enters at IPO time
    # (see player_service.create_player); the server_default only matters
    # for this one-time backfill.
    op.add_column('players', sa.Column('power_rating', sa.Integer(), nullable=False, server_default='65'))


def downgrade() -> None:
    op.drop_column('players', 'power_rating')
