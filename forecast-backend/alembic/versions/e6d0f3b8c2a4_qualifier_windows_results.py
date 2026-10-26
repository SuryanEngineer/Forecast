"""qualifier windows + results (earlier rounds of a Finals event)

Revision ID: e6d0f3b8c2a4
Revises: d5c9e2a7b1f3
Create Date: 2026-10-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e6d0f3b8c2a4'
down_revision = 'd5c9e2a7b1f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qualifier_windows',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('tournament_id', sa.UUID(), sa.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('osirion_event_id', sa.String(160), nullable=False),
        sa.Column('event_window_id', sa.String(160), nullable=False),
        sa.Column('leaderboard_event_id', sa.String(160), nullable=False),
        sa.Column('leaderboard_event_window_id', sa.String(160), nullable=False),
        sa.Column('display_name', sa.String(300), nullable=True),
        sa.Column('stage_index', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('begin_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('advance_cutoff', sa.Integer(), nullable=True),
        sa.Column('field_estimate', sa.Integer(), nullable=True),
        sa.Column('total_pages', sa.Integer(), nullable=True),
        sa.Column('next_page', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entries_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_complete', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('capped', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tournament_id', 'leaderboard_event_id', 'leaderboard_event_window_id', name='uq_qualifier_window'),
    )
    op.create_index('ix_qualifier_windows_tournament_id', 'qualifier_windows', ['tournament_id'])

    op.create_table(
        'qualifier_results',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('window_id', sa.UUID(), sa.ForeignKey('qualifier_windows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tournament_id', sa.UUID(), sa.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('player_id', sa.UUID(), sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('percentile', sa.Numeric(8, 4), nullable=True),
        sa.Column('points', sa.Numeric(10, 2), nullable=True),
        sa.Column('team_id', sa.Text(), nullable=True),
        sa.Column('team_size', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('teammate_player_ids', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('window_id', 'player_id', name='uq_qualifier_result'),
    )
    op.create_index('ix_qualifier_results_window_id', 'qualifier_results', ['window_id'])
    op.create_index('ix_qualifier_results_tournament_id', 'qualifier_results', ['tournament_id'])
    op.create_index('ix_qualifier_results_player_id', 'qualifier_results', ['player_id'])
    for t in ('qualifier_windows', 'qualifier_results'):
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    op.drop_table('qualifier_results')
    op.drop_table('qualifier_windows')
