"""add tournament classification rules + region multipliers

Revision ID: e5a2c8d1f9b3
Revises: d4f7b3c9a1e6
Create Date: 2026-09-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e5a2c8d1f9b3'
down_revision = 'd4f7b3c9a1e6'
branch_labels = None
depends_on = None

# The `tournament_type` enum TYPE already exists in Postgres (created by
# 0a9985470bd6_initial_schema for the `tournaments` table itself) --
# create_type=False so this migration reuses it instead of trying (and
# failing) to CREATE TYPE a second time. On SQLite (demo mode) this
# compiles down to a plain VARCHAR + CHECK constraint either way, so
# create_type is a no-op there.
TOURNAMENT_TYPE_ENUM = postgresql.ENUM(
    'cash_cup', 'fncs_qualifier', 'fncs_finals', 'global_championship', 'major', 'other',
    name='tournament_type',
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        'tournament_classification_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pattern', sa.String(length=200), nullable=False),
        sa.Column('tournament_type', TOURNAMENT_TYPE_ENUM, nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'region_multipliers',
        sa.Column('region', sa.String(length=50), nullable=False),
        sa.Column('multiplier', sa.Numeric(6, 4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('region'),
    )


def downgrade() -> None:
    op.drop_table('region_multipliers')
    op.drop_table('tournament_classification_rules')
