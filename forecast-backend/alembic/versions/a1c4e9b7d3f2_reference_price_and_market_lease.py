"""players.reference_price + market_lease (single-writer lock)

Revision ID: a1c4e9b7d3f2
Revises: f7a2d5c8e1b6
Create Date: 2026-10-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1c4e9b7d3f2'
down_revision = 'f7a2d5c8e1b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The market's running opinion of a stock's price (see app/engine/market_policy.py). NULL = not set yet; readers
    # fall back to the last price point, then the IPO price.
    op.add_column('players', sa.Column('reference_price', sa.Numeric(18, 4), nullable=True))
    # One row per named lock. The web server that holds the 'market' lock is the only process allowed to match orders
    # (the order books live in memory), see app/services/lease_service.py.
    op.create_table(
        'market_lease',
        sa.Column('name', sa.String(length=32), nullable=False),
        sa.Column('holder', sa.String(length=80), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )
    op.execute('ALTER TABLE public."market_lease" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    op.drop_table('market_lease')
    op.drop_column('players', 'reference_price')
