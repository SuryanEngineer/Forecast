"""add player_aliases (LAN account names -> player)

Revision ID: a6d2e8f1c3b7
Revises: e7f3a9c2d4b1
Create Date: 2026-10-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a6d2e8f1c3b7'
down_revision = 'e7f3a9c2d4b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'player_aliases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('alias_key', sa.String(length=200), nullable=False),
        sa.Column('alias_name', sa.String(length=200), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_player_aliases_alias_key'), 'player_aliases', ['alias_key'], unique=True)
    op.create_index(op.f('ix_player_aliases_player_id'), 'player_aliases', ['player_id'], unique=False)
    # Same deny-all RLS posture as every other public table (see e7f3a9c2d4b1).
    op.execute('ALTER TABLE public."player_aliases" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    op.drop_index(op.f('ix_player_aliases_player_id'), table_name='player_aliases')
    op.drop_index(op.f('ix_player_aliases_alias_key'), table_name='player_aliases')
    op.drop_table('player_aliases')
