"""notifications table + performance_eval tournament tier

Revision ID: c6f2b8d4a1e9
Revises: b3d7f1a2c9e4
Create Date: 2026-11-06 12:00:00.000000

* notifications: in-app notification feed (trades, cancellations, dividends, tournaments, game wins).
* tournament_type gains 'performance_eval' (set-lobby Performance Evaluation cups, paid per game won). The existing
  classification rule for "performance evaluation" used to be an exclude (NULL type); it is flipped to the new tier.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c6f2b8d4a1e9'
down_revision = 'b3d7f1a2c9e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ADD VALUE cannot run inside the migration's transaction on older Postgres versions: commit around it.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE tournament_type ADD VALUE IF NOT EXISTS 'performance_eval'")

    op.create_table(
        'notifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON(), nullable=True),
        sa.Column('ref_key', sa.String(length=160), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()') if bind.dialect.name == "postgresql" else sa.func.now(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'ref_key', name='uq_notification_user_ref'),
    )
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'])
    if bind.dialect.name == "postgresql":
        # Same reasoning as e7f3a9c2d4b1: deny-all for Supabase's anon/authenticated roles; the backend (table owner) is unaffected.
        op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
        # Now (in a fresh transaction) the new enum value can be used: Performance Evaluation cups are a tier, not excluded.
        op.execute(
            "UPDATE tournament_classification_rules SET tournament_type = 'performance_eval' "
            "WHERE lower(pattern) = 'performance evaluation' AND tournament_type IS NULL"
        )


def downgrade() -> None:
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_table('notifications')
    # (A Postgres enum value cannot be removed; 'performance_eval' stays in the type.)
