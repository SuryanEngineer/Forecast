"""
Dialect-portable column types.

Every model in this app was originally written against
`sqlalchemy.dialects.postgresql.UUID`/`JSONB` directly, which only exist
on Postgres -- fine for the real product (Supabase), but it means the
exact same ORM models can't create a schema on SQLite, which is what
demo mode (see app/core/config.py's DEMO_MODE, and DEMO_MODE.md) uses so
someone can run the whole app with zero external services.

`GUID` and `JSONType` below are the standard SQLAlchemy "backend-agnostic
type" recipe (TypeDecorator): on Postgres they compile to the exact same
native `UUID`/`JSONB` columns as before (byte-for-byte identical DDL to
what the existing Alembic migrations already created -- this file changes
no behavior for the real database), and on any other dialect (SQLite, in
practice) they fall back to a portable CHAR(36)/JSON representation. The
Python-level value is always a `uuid.UUID` (for GUID) or a plain
dict/list (for JSONType) regardless of which dialect is underneath --
model code and service code never need to know which database they're
talking to.

Note for later: SQLAlchemy/Alembic's autogenerate type-comparison looks
at `TypeDecorator.impl` (CHAR / JSON) rather than what
`load_dialect_impl` actually renders, so running
`alembic revision --autogenerate` against the real Postgres database
after this change may propose a spurious "type changed" diff even though
the compiled column type on Postgres is unchanged. If that happens, it's
noise -- do not apply a migration that would actually alter the column
type in Postgres.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.types import CHAR, JSON, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent UUID type. Postgres: native UUID. Anything
    else (SQLite): CHAR(36), storing the canonical hyphenated string form.
    Always yields a Python `uuid.UUID` back to calling code."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONType(TypeDecorator):
    """Platform-independent JSON type. Postgres: native JSONB (same
    `astext_type=Text()` config the original hand-written columns used).
    Anything else (SQLite): plain JSON (SQLAlchemy's generic JSON type,
    which SQLite stores as TEXT and (de)serializes transparently)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB(astext_type=sa.Text()))
        return dialect.type_descriptor(JSON())
