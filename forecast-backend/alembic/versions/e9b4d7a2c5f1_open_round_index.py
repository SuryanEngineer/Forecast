"""open round search index (finished open qualifier rounds)

Revision ID: e9b4d7a2c5f1
Revises: d8a3c5e1f7b2
Create Date: 2026-11-10 14:00:00.000000

Two small tables: the per-round indexing cursor and the compact (name, rank, points) rows used to search finished open
qualifier rounds. See app/models/open_round.py.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e9b4d7a2c5f1'
down_revision = 'd8a3c5e1f7b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    now = sa.text('now()') if pg else sa.func.now()
    op.create_table(
        'open_round_index_state',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('leaderboard_event_id', sa.String(length=160), nullable=False),
        sa.Column('leaderboard_event_window_id', sa.String(length=160), nullable=False),
        sa.Column('display_name', sa.String(length=300), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_pages', sa.Integer(), nullable=True),
        sa.Column('next_page', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entries_indexed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_complete', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('capped', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=now, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('leaderboard_event_id', 'leaderboard_event_window_id', name='uq_open_round_state'),
    )
    op.create_table(
        'open_round_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('state_id', sa.UUID(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('name_lc', sa.String(length=80), nullable=False),
        sa.Column('points', sa.Numeric(10, 2), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('state_id', 'rank', 'name_lc', name='uq_open_round_entry'),
    )
    op.create_index('ix_open_round_entries_state_id', 'open_round_entries', ['state_id'])
    op.create_index('ix_open_round_entries_name_lc', 'open_round_entries', ['name_lc'])
    if pg:
        # Same reasoning as e7f3a9c2d4b1: deny-all for Supabase's anon/authenticated roles; the backend (table owner) is unaffected.
        op.execute("ALTER TABLE open_round_index_state ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE open_round_entries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index('ix_open_round_entries_name_lc', table_name='open_round_entries')
    op.drop_index('ix_open_round_entries_state_id', table_name='open_round_entries')
    op.drop_table('open_round_entries')
    op.drop_table('open_round_index_state')
