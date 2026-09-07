"""
FastAPI application entrypoint.

Run locally with:  uvicorn app.main:app --reload
(see README_SETUP.md for the full setup sequence -- database migration,
.env file, etc. -- this will fail fast with a clear connection error if
DATABASE_URL isn't reachable yet, which is expected before you've done
that setup).
"""
import asyncio
import logging
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import admin, auctions, auth, dividends, leaderboard, markets, orders, players, tournaments, treasury, wallet, ws
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.services import bot_trading_service, osirion_service

logger = logging.getLogger("forecast.bots")
osirion_logger = logging.getLogger("forecast.osirion")


def _run_one_bot_tick(rng: random.Random) -> None:
    """Runs on a worker thread (see asyncio.to_thread below) with its own
    plain SessionLocal(), NOT the request-scoped `get_db` dependency --
    there is no HTTP request driving this, it's a background loop."""
    db = SessionLocal()
    try:
        result = bot_trading_service.run_bot_tick(db, rng)
        logger.info("Bot tick: %s", result)
    finally:
        db.close()


async def _bot_tick_loop() -> None:
    """Runs for the lifetime of the process (see `lifespan` below). A
    short initial delay lets the app finish starting before the first DB
    hit; after that it ticks on BOT_TICK_INTERVAL_SECONDS. Any exception
    from a single tick is logged and swallowed -- one bad tick (e.g. a
    momentary DB hiccup) should never kill bot trading for the rest of
    the process's life, since there's no supervisor restarting this loop
    the way `uvicorn --reload` restarts the whole process on a code
    change."""
    rng = random.Random()
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.to_thread(_run_one_bot_tick, rng)
        except Exception:
            logger.exception("Bot tick failed -- will retry next interval.")
        await asyncio.sleep(settings.BOT_TICK_INTERVAL_SECONDS)


def _run_one_osirion_sync() -> None:
    """Runs on a worker thread, its own plain SessionLocal() -- same
    pattern as `_run_one_bot_tick` above. Auto-tracks any newly-eligible
    tournament first (see osirion_service.auto_track_new_tournaments,
    gated on settings.OSIRION_AUTO_TRACK_ENABLED), then syncs standings
    for everything currently tracked -- a no-op sync (queries zero
    mappings) until at least one tournament is tracked, whether that
    happened automatically or via the manual admin endpoint."""
    db = SessionLocal()
    try:
        if settings.OSIRION_AUTO_TRACK_ENABLED:
            auto_track_result = osirion_service.auto_track_new_tournaments(db)
            if auto_track_result.tracked or auto_track_result.errors:
                osirion_logger.info(
                    "Osirion auto-track: seen=%d tracked=%d skipped_already=%d skipped_unclassified=%d "
                    "skipped_season_dedup=%d errors=%s",
                    auto_track_result.windows_seen, auto_track_result.tracked,
                    auto_track_result.skipped_already_tracked, auto_track_result.skipped_unclassified,
                    auto_track_result.skipped_season_dedup, auto_track_result.errors,
                )

        results = osirion_service.sync_all_tracked(db)
        for result in results:
            if result.error:
                osirion_logger.warning("Osirion sync error for tournament %s: %s", result.tournament_id, result.error)
            elif result.matched or result.unmatched_usernames:
                osirion_logger.info(
                    "Osirion sync: tournament=%s matched=%d unmatched=%s finalized=%s",
                    result.tournament_id, result.matched, result.unmatched_usernames, result.finalized,
                )
    finally:
        db.close()


async def _osirion_sync_loop() -> None:
    """Runs for the lifetime of the process (see `lifespan` below), same
    pattern as `_bot_tick_loop`. See app/services/osirion_service.py for
    what an actual sync pass does."""
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(_run_one_osirion_sync)
        except Exception:
            osirion_logger.exception("Osirion sync pass failed -- will retry next interval.")
        await asyncio.sleep(settings.OSIRION_SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks: list[asyncio.Task] = []

    if not settings.REDIS_ENABLED:
        # The in-process pub/sub substitute for the live price feed
        # (app/services/local_pubsub.py) needs a reference to this loop
        # so it can safely deliver messages published from worker
        # threads (sync route handlers, asyncio.to_thread calls). This is
        # independent of DEMO_MODE -- see config.py's REDIS_ENABLED.
        from app.services import local_pubsub

        local_pubsub.bind_loop(asyncio.get_running_loop())

    if settings.DEMO_MODE:
        # No Alembic in demo mode -- the ORM models (app/db/base.py's
        # Base.metadata, fully populated once app.models is imported,
        # which app.api.v1's routers already trigger transitively) are
        # the schema source of truth. create_all only creates tables that
        # don't already exist, so this is safe to run on every startup.
        from app.db.base import Base

        Base.metadata.create_all(bind=engine)

        from app.services.demo_tournament_service import demo_tournament_loop

        tasks.append(asyncio.create_task(demo_tournament_loop()))

    if settings.BOT_TRADING_ENABLED:
        tasks.append(asyncio.create_task(_bot_tick_loop()))

    if settings.OSIRION_SYNC_ENABLED:
        tasks.append(asyncio.create_task(_osirion_sync_loop()))

    yield

    for task in tasks:
        task.cancel()


app = FastAPI(
    title="Forecast API",
    description="Backend for the Forecast fantasy Fortnite stock market.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(wallet.router, prefix=API_PREFIX)
app.include_router(players.router, prefix=API_PREFIX)
app.include_router(orders.router, prefix=API_PREFIX)
app.include_router(tournaments.router, prefix=API_PREFIX)
app.include_router(dividends.router, prefix=API_PREFIX)
app.include_router(treasury.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(auctions.router, prefix=API_PREFIX)
app.include_router(markets.router, prefix=API_PREFIX)
app.include_router(leaderboard.router, prefix=API_PREFIX)
app.include_router(ws.router, prefix=API_PREFIX)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.ENV}
