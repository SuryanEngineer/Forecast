"""add share_transfers (timestamped share-movement ledger)

Revision ID: c4a8d1e6f2b9
Revises: b9e3f7a2d1c4
Create Date: 2026-10-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c4a8d1e6f2b9'
down_revision = 'b9e3f7a2d1c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'share_transfers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_share_transfers_user_id'), 'share_transfers', ['user_id'], unique=False)
    op.create_index(op.f('ix_share_transfers_player_id'), 'share_transfers', ['player_id'], unique=False)
    op.create_index(op.f('ix_share_transfers_occurred_at'), 'share_transfers', ['occurred_at'], unique=False)
    # Same deny-all RLS posture as every other public table (see e7f3a9c2d4b1).
    op.execute('ALTER TABLE public."share_transfers" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    op.drop_index(op.f('ix_share_transfers_occurred_at'), table_name='share_transfers')
    op.drop_index(op.f('ix_share_transfers_player_id'), table_name='share_transfers')
    op.drop_index(op.f('ix_share_transfers_user_id'), table_name='share_transfers')
    op.drop_table('share_transfers')
