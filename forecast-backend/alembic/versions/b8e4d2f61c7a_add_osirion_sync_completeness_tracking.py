"""add osirion sync completeness tracking (last_sync_complete + seeded heat windows)

Revision ID: b8e4d2f61c7a
Revises: a2c4e9f0b1d7
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b8e4d2f61c7a'
down_revision = 'a2c4e9f0b1d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'osirion_tournament_mappings',
        sa.Column('last_sync_complete', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    op.create_table(
        'osirion_seeded_heat_windows',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('leaderboard_event_id', sa.String(length=64), nullable=False),
        sa.Column('leaderboard_event_window_id', sa.String(length=64), nullable=False),
        sa.Column('seeded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'leaderboard_event_id', 'leaderboard_event_window_id', name='uq_seeded_heat_window'
        ),
    )


def downgrade() -> None:
    op.drop_table('osirion_seeded_heat_windows')
    op.drop_column('osirion_tournament_mappings', 'last_sync_complete')
