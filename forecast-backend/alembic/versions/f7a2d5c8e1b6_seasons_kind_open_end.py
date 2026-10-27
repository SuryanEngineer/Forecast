"""seasons: kind + nullable end date (Fortnite calendar, TBD end)

Revision ID: f7a2d5c8e1b6
Revises: e6d0f3b8c2a4
Create Date: 2026-10-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a2d5c8e1b6'
down_revision = 'e6d0f3b8c2a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('seasons', sa.Column('kind', sa.String(20), nullable=False, server_default='season'))
    op.alter_column('seasons', 'ends_at', existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE seasons SET ends_at = starts_at + interval '120 days' WHERE ends_at IS NULL")
    op.alter_column('seasons', 'ends_at', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column('seasons', 'kind')
