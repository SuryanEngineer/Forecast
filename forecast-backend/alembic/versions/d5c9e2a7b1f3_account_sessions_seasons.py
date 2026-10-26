"""account fields, sessions, email codes, portfolio snapshots, seasons

Revision ID: d5c9e2a7b1f3
Revises: c4a8d1e6f2b9
Create Date: 2026-10-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5c9e2a7b1f3'
down_revision = 'c4a8d1e6f2b9'
branch_labels = None
depends_on = None

_RLS = ['user_sessions', 'email_codes', 'portfolio_snapshots', 'seasons', 'season_entries']


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('tag', sa.String(5), nullable=True))
        b.add_column(sa.Column('tag_color', sa.String(9), nullable=True))
        b.add_column(sa.Column('display_name_changed_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('login_count', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'user_sessions',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('active_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('heartbeats', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ip_address', sa.String(64), nullable=True),
        sa.Column('user_agent', sa.String(300), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='login'),
    )
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
    op.create_index('ix_user_sessions_started_at', 'user_sessions', ['started_at'])

    op.create_table(
        'email_codes',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('purpose', sa.String(30), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('target_email', sa.String(255), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_email_codes_user_id', 'email_codes', ['user_id'])
    op.create_index('ix_email_codes_created_at', 'email_codes', ['created_at'])

    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.String(10), nullable=False),
        sa.Column('net_worth', sa.Numeric(18, 4), nullable=False),
        sa.Column('cash', sa.Numeric(18, 4), nullable=False),
        sa.Column('holdings_value', sa.Numeric(18, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'day', name='uq_portfolio_snapshot_user_day'),
    )
    op.create_index('ix_portfolio_snapshots_user_id', 'portfolio_snapshots', ['user_id'])
    op.create_index('ix_portfolio_snapshots_day', 'portfolio_snapshots', ['day'])

    op.create_table(
        'seasons',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_seasons_is_active', 'seasons', ['is_active'])

    op.create_table(
        'season_entries',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('season_id', sa.UUID(), sa.ForeignKey('seasons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_value', sa.Numeric(18, 4), nullable=False),
        sa.Column('final_value', sa.Numeric(18, 4), nullable=True),
        sa.Column('final_points', sa.Integer(), nullable=True),
        sa.Column('final_rank', sa.String(20), nullable=True),
        sa.Column('final_position', sa.Integer(), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('season_id', 'user_id', name='uq_season_entry_user'),
    )
    op.create_index('ix_season_entries_season_id', 'season_entries', ['season_id'])
    op.create_index('ix_season_entries_user_id', 'season_entries', ['user_id'])

    for t in _RLS:
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    for t in ['season_entries', 'seasons', 'portfolio_snapshots', 'email_codes', 'user_sessions']:
        op.drop_table(t)
    with op.batch_alter_table('users') as b:
        for c in ['locked_until', 'failed_login_count', 'login_count', 'last_seen_at', 'last_login_at', 'password_changed_at',
                  'terms_accepted_at', 'email_verified_at', 'display_name_changed_at', 'tag_color', 'tag']:
            b.drop_column(c)
