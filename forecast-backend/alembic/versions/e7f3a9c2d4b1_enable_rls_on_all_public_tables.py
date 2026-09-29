"""enable row level security on every public table

Revision ID: e7f3a9c2d4b1
Revises: d3b8f6a1c4e9
Create Date: 2026-09-29

Supabase's own security linter flags every table in the public schema as
"RLS Disabled in Public" / Critical the moment it's created, because
Supabase exposes the whole database through a separate auto-generated
REST API (PostgREST) that any caller can hit directly with the project's
"anon" API key -- completely independent of this app's own FastAPI
backend. Without RLS, anyone who obtains that key (which Supabase treats
as safe to expose publicly ONLY when RLS is properly locked down) could
read or write every row in every one of these tables straight through
that REST endpoint, bypassing this app's auth/business logic entirely.

This app never uses Supabase's client SDK, its auth system, or that REST
API -- the backend talks to Postgres directly via DATABASE_URL, connecting
as the `postgres` role (Supabase's pooler username convention is
`postgres.<project-ref>`), which is either a superuser or the owner of
every table created through it (since Alembic itself runs through this
same connection). Both superusers and table owners bypass Row Level
Security automatically, REGARDLESS of whether RLS is enabled and
REGARDLESS of whether any policies exist -- see the "Row security and
superusers" section of the Postgres 17 docs
(https://www.postgresql.org/docs/current/ddl-rowsecurity.html) for exactly
this behavior.

Net effect of this migration: enabling RLS with zero policies switches
every one of these tables to deny-all for any OTHER role (specifically
Supabase's `anon`/`authenticated` PostgREST roles) while having ZERO
effect on this application, since every query this backend makes already
runs as the table-owning role. It's the cheapest possible fix for the
linter's finding -- closing a real (if currently unused) access path --
without writing per-table policies this app doesn't otherwise need. If a
future feature ever needs Supabase's REST API or client-side access to a
specific table for `anon`/`authenticated`, add an explicit CREATE POLICY
for that table's real access rules -- don't just disable RLS again.
"""
from __future__ import annotations

from alembic import op

revision = "e7f3a9c2d4b1"
down_revision = "d3b8f6a1c4e9"
branch_labels = None
depends_on = None

# Verbatim list of every table Supabase's linter flagged.
TABLES = [
    "alembic_version",
    "audit_log",
    "dividend_placement_curve",
    "users",
    "auction_rounds",
    "orders",
    "players",
    "platform_parameters",
    "positions",
    "price_snapshots",
    "tournaments",
    "trades",
    "treasury_instruments",
    "treasury_holdings",
    "wallets",
    "auction_bids",
    "auction_participants",
    "dividend_payouts",
    "ledger_entries",
    "osirion_tournament_mappings",
    "treasury_accrual_log",
    "dividend_line_items",
    "bot_profiles",
    "password_reset_tokens",
    "osirion_player_mappings",
    "tournament_classification_rules",
    "region_multipliers",
    "tournament_entrants",
    "placement_results",
    "tournament_result_archives",
    "osirion_seeded_heat_windows",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY;')
