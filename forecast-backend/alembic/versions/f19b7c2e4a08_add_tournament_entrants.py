"""add tournament entrants (pre-results qualified roster)

Revision ID: f19b7c2e4a08
Revises: e5a2c8d1f9b3
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f19b7c2e4a08'
down_revision = 'e5a2c8d1f9b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tournament_entrants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tournament_id', sa.UUID(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_id', 'player_id', name='uq_tournament_entrant'),
    )
    op.create_index(op.f('ix_tournament_entrants_tournament_id'), 'tournament_entrants', ['tournament_id'], unique=False)
    op.create_index(op.f('ix_tournament_entrants_player_id'), 'tournament_entrants', ['player_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tournament_entrants_player_id'), table_name='tournament_entrants')
    op.drop_index(op.f('ix_tournament_entrants_tournament_id'), table_name='tournament_entrants')
    op.drop_table('tournament_entrants')
