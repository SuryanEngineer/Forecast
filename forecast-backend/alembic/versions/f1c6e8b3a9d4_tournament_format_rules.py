"""tournament format rules (lobby / stage / cash / scoring / pool)

Revision ID: f1c6e8b3a9d4
Revises: e9b4d7a2c5f1
Create Date: 2026-11-10 18:00:00.000000

One nullable JSON column on tournaments. Null = the tier's default pool (every tournament tracked before the format rules).
See app/engine/format_policy.py.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1c6e8b3a9d4'
down_revision = 'e9b4d7a2c5f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tournaments', sa.Column('format_rules', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tournaments', 'format_rules')
