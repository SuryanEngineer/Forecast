"""orders.expires_at (optional time limit on limit orders)

Revision ID: b3d7f1a2c9e4
Revises: a1c4e9b7d3f2
Create Date: 2026-10-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3d7f1a2c9e4'
down_revision = 'a1c4e9b7d3f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = good until cancelled (the default). Otherwise a sweep cancels the order at that time and releases its hold.
    op.add_column('orders', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'expires_at')
