"""
Central settings object, populated from environment variables / a .env
file (see .env.example for every variable this app reads, with comments
on where to get each value for free).

Which .env file gets read is controlled by the FORECAST_ENV_FILE
environment variable (defaults to ".env", the real Postgres/Redis-backed
setup). Demo mode (see DEMO_MODE below and DEMO_MODE.md) runs with
FORECAST_ENV_FILE=.env.demo set before startup, so the two configs never
collide and nothing about the real .env changes.
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("FORECAST_ENV_FILE", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database (Postgres in production; SQLite in demo mode) ---
    DATABASE_URL: str = "postgresql+psycopg2://forecast:forecast@localhost:5432/forecast"

    # --- Redis (order book pub/sub, WebSocket fanout, RQ job queue) ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # Independent of DEMO_MODE (see below). When false, the app never
    # touches Redis at all: app/services/price_feed.py and app/api/v1/ws.py
    # fan out live prices via the in-process pub/sub substitute
    # (app/services/local_pubsub.py) instead of Redis pub/sub, and
    # app/jobs/tasks.py runs "background" jobs (dividend payouts, treasury
    # accrual, bot-quote refresh) synchronously in-process instead of
    # enqueuing them on an RQ queue that would otherwise need a separate
    # `rq worker` process to ever drain.
    #
    # This matters for a real (non-demo) single-instance deploy on a free
    # hosting tier: there's no second process available to run an RQ
    # worker, so REDIS_ENABLED=false is the correct production setting
    # there too, not just for DEMO_MODE. It's a pure infrastructure
    # switch -- it has no bearing on economics, tournament data, or
    # anything else "real" about the deploy. Flip it to true (and set a
    # real REDIS_URL) only once you're running multiple instances of this
    # app and actually need Redis to fan work out across them, at which
    # point you'd also run a separate `rq worker` process/service.
    REDIS_ENABLED: bool = True

    # --- Demo mode ---
    # When true: DATABASE_URL is expected to be a local SQLite file,
    # schema is created directly from the ORM models (no Alembic), and a
    # background loop auto-generates randomized tournament results so a
    # visitor sees the market move without an admin doing anything (see
    # app/services/demo_tournament_service.py). This is ONLY about fake
    # data/schema convenience for a zero-setup sandbox -- it has nothing
    # to do with Redis any more (see REDIS_ENABLED above). Never enable
    # this for the real production deploy: it bypasses Alembic migrations
    # and fabricates tournament results. See DEMO_MODE.md for the full
    # picture.
    DEMO_MODE: bool = False

    # How often (seconds) demo mode runs a randomized tournament on its
    # own, so a visitor watching the market sees prices move and
    # dividends pay out without needing an admin to do anything. Unused
    # outside demo mode. See app/services/demo_tournament_service.py.
    DEMO_TOURNAMENT_INTERVAL_SECONDS: int = 180

    # --- Auth ---
    JWT_SECRET_KEY: str = "CHANGE_ME_INSECURE_DEFAULT"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # --- Forgot-password email ---
    # See app/services/email_service.py. "console" (the default) just logs
    # the reset link server-side -- nothing is emailed. That's a real gap
    # for real users, but it needs zero setup, so it's the default until
    # you pick a provider. Switch EMAIL_PROVIDER to "resend" (recommended
    # -- resend.com, free tier, sign up and get an API key) once you're
    # ready; everything else in this app is already wired for it.
    EMAIL_PROVIDER: str = "console"  # "console" | "resend"
    RESEND_API_KEY: str | None = None
    EMAIL_FROM_ADDRESS: str = "Forecast <onboarding@resend.dev>"
    # The public URL of the deployed FRONTEND (not the API) -- used to
    # build the link inside the password-reset email, e.g.
    # "https://forecast-app.onrender.com". Left as localhost for local dev.
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # --- Platform economics: one-time seed values only ---
    # DEFAULT_TREASURY_ANNUAL_RATE seeds the very first TreasuryInstrument
    # row the first time /treasury/instrument is requested; after that,
    # the database (TreasuryInstrument table) is the source of truth --
    # change the rate going forward via POST /admin/treasury/rate, not by
    # editing this value. Every OTHER economic knob (quick buy/sell
    # slippage, dividend platform fee, bot liquidity ladder shape) lives
    # entirely in the `platform_parameters` table from the start -- see
    # app/services/economic_params_service.py -- and has no .env
    # equivalent at all, specifically so it's changeable from the admin
    # API without a deploy.
    DEFAULT_TREASURY_ANNUAL_RATE: float = 0.01  # 1% APY starting rate -- matches the validated
    # economy simulation's ~1%/year cash treasury yield (0.02% per tournament x ~50 tournaments/chapter).

    # --- Misc ---
    ENV: str = "development"
    CORS_ORIGINS: str = "*"

    # --- Osirion live tournament data (app/services/osirion_service.py,
    # app/integrations/osirion_client.py) ---
    # Public beta API, no key currently required/available -- see
    # https://fnapi.osirion.gg/docs. Only matters once an admin has
    # actually tracked at least one tournament (POST
    # /admin/osirion/track-tournament); with nothing tracked yet the sync
    # loop just wakes up, finds nothing to do, and goes back to sleep.
    OSIRION_API_BASE_URL: str = "https://fnapi.osirion.gg"
    OSIRION_SYNC_ENABLED: bool = True
    # Osirion's own docs cap the leaderboard endpoint at 60 req/min; each
    # tracked tournament can take more than one request per sync (one per
    # leaderboard page). Keep this well above 1 request/sec if you end up
    # tracking many tournaments at once.
    OSIRION_SYNC_INTERVAL_SECONDS: int = 45
    # When true (default), every sync pass also calls
    # osirion_service.auto_track_new_tournaments FIRST: classifies every
    # currently-open Osirion window (via the admin-editable
    # TournamentClassificationRule table -- see
    # app/services/tournament_classification_service.py) and starts
    # tracking anything that matches a wanted tier, with no admin action
    # needed. Set to false to go back to the old fully-manual flow (POST
    # /admin/osirion/track-tournament for every tournament).
    OSIRION_AUTO_TRACK_ENABLED: bool = True

    # --- Bot trading loop (app/services/bot_trading_service.py) ---
    # This is operational config (is the loop running at all, how often),
    # not economic policy -- the actual trading behavior (sizing,
    # strategy weights, etc.) lives in the database via
    # economic_params_service.py's "bots.*" keys so it's admin-tunable
    # without a restart. These two are here instead because changing them
    # DOES require restarting the process (they control the background
    # asyncio task started in main.py's lifespan).
    BOT_TRADING_ENABLED: bool = True
    BOT_TICK_INTERVAL_SECONDS: int = 20


settings = Settings()
