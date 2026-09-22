"""widen placement_results.team_id from varchar(100) to text

Revision ID: d3b8f6a1c4e9
Revises: c9a1f4e7d2b5
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd3b8f6a1c4e9'
down_revision = 'c9a1f4e7d2b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A 4-player squad's Osirion teamId (every teammate's accountId
    # concatenated with colons) is up to 131 characters -- over the old
    # VARCHAR(100) limit. Duos/solos always fit under 100, which is why
    # this went unnoticed until a real squad-format tournament was synced.
    op.alter_column(
        'placement_results',
        'team_id',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'placement_results',
        'team_id',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
