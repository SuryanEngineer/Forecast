"""add osirion tournament/player mappings

Revision ID: d4f7b3c9a1e6
Revises: c3e8a1f5b6d2
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4f7b3c9a1e6'
down_revision = 'c3e8a1f5b6d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'osirion_tournament_mappings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tournament_id', sa.UUID(), nullable=False),
        sa.Column('osirion_event_id', sa.String(length=64), nullable=False),
        sa.Column('osirion_event_window_id', sa.String(length=64), nullable=False),
        sa.Column('leaderboard_event_id', sa.String(length=64), nullable=False),
        sa.Column('leaderboard_event_window_id', sa.String(length=64), nullable=False),
        sa.Column('osirion_display_name', sa.String(length=300), nullable=True),
        sa.Column('window_begin_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_id', name='uq_osirion_tournament_mapping_tournament'),
    )
    op.create_index(
        op.f('ix_osirion_tournament_mappings_tournament_id'), 'osirion_tournament_mappings', ['tournament_id'], unique=True
    )

    op.create_table(
        'osirion_player_mappings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('osirion_account_id', sa.String(length=64), nullable=False),
        sa.Column('osirion_username', sa.String(length=100), nullable=True),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_osirion_player_mappings_osirion_account_id'),
        'osirion_player_mappings', ['osirion_account_id'], unique=True,
    )
    op.create_index(op.f('ix_osirion_player_mappings_player_id'), 'osirion_player_mappings', ['player_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_osirion_player_mappings_player_id'), table_name='osirion_player_mappings')
    op.drop_index(op.f('ix_osirion_player_mappings_osirion_account_id'), table_name='osirion_player_mappings')
    op.drop_table('osirion_player_mappings')
    op.drop_index(op.f('ix_osirion_tournament_mappings_tournament_id'), table_name='osirion_tournament_mappings')
    op.drop_table('osirion_tournament_mappings')
