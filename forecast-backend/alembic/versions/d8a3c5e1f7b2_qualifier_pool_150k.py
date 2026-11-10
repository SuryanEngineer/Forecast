"""qualifier pool default 300,000 -> 150,000

Revision ID: d8a3c5e1f7b2
Revises: c6f2b8d4a1e9
Create Date: 2026-11-10 12:00:00.000000

Set-lobby qualifiers (FNCS Solo Reload Heats / Last Chance Qualifier) now pay a $150,000 pool. The code default changed;
this updates an already-stored value, but ONLY if it is still the old default (an admin-tuned value is left alone).
"""
from alembic import op

revision = 'd8a3c5e1f7b2'
down_revision = 'c6f2b8d4a1e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE platform_parameters SET value = 150000 "
        "WHERE key = 'dividend.qualifier_pool' AND value = 300000"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE platform_parameters SET value = 300000 "
        "WHERE key = 'dividend.qualifier_pool' AND value = 150000"
    )
