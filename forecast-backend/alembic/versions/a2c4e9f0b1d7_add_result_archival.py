"""add raw result archival (placement_results extra fields + tournament_result_archives)

Revision ID: a2c4e9f0b1d7
Revises: f19b7c2e4a08
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a2c4e9f0b1d7'
down_revision = 'f19b7c2e4a08'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('placement_results', sa.Column('team_id', sa.String(length=100), nullable=True))
    op.add_column('placement_results', sa.Column('percentile', sa.Numeric(6, 3), nullable=True))
    op.add_column('placement_results', sa.Column('raw_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        'tournament_result_archives',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tournament_id', sa.UUID(), nullable=False),
        sa.Column('raw_tournament_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_leaderboard_entries', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_id', name='uq_tournament_result_archive_tournament'),
    )
    op.create_index(
        op.f('ix_tournament_result_archives_tournament_id'), 'tournament_result_archives', ['tournament_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_tournament_result_archives_tournament_id'), table_name='tournament_result_archives')
    op.drop_table('tournament_result_archives')

    op.drop_column('placement_results', 'raw_stats')
    op.drop_column('placement_results', 'percentile')
    op.drop_column('placement_results', 'team_id')
