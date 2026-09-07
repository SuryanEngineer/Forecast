"""
Engine/session setup. Reads DATABASE_URL from environment (see
app/core/config.py and .env.example). Use `get_db` as a FastAPI dependency
-- it yields one session per request and always closes it.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

if settings.DATABASE_URL.startswith("sqlite"):
    # Demo mode: a local SQLite file. check_same_thread=False is required
    # because this engine gets hit from more than one thread -- FastAPI
    # runs sync `def` route handlers in a threadpool, and the bot-tick /
    # demo-tournament background loops call into service code via
    # asyncio.to_thread. SQLite's own single-writer file locking (not
    # connection pooling) is what actually keeps writes safe here, which
    # is fine at demo scale. pool_pre_ping is skipped too -- it only
    # matters for a network database that can idle-timeout you.
    engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False}, future=True)
else:
    # pool_pre_ping avoids "server closed the connection unexpectedly" errors
    # from free-tier Postgres providers (Supabase/Neon) that idle-timeout
    # connections after a few minutes.
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
