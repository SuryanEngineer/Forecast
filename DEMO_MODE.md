# Demo mode

A second, fully self-contained way to run Forecast: no Postgres account,
no Redis account, no cloud services at all. It's the *exact same* trading
engine, order matching, dividend math, and bot population as the real
product -- just pointed at a local SQLite file instead of Supabase, with
a couple of Redis-only features swapped for in-process equivalents. The
goal is that anyone can clone the repo and have a working, populated,
self-playing market running in a couple of minutes, with zero setup and
zero risk of touching the real database.

It exists for two reasons: letting people try the product without an
account/API keys, and giving you something to demo to potential users or
sponsors that behaves like the real thing rather than a static mockup.

## What's different from the real product

| | Real product | Demo mode |
|---|---|---|
| Database | Postgres (Supabase) | Local SQLite file (`forecast-backend/demo.db`) |
| Schema setup | Alembic migrations | `Base.metadata.create_all()` -- no migration history needed |
| Live price feed | Redis pub/sub | In-process pub/sub (`app/services/local_pubsub.py`) |
| Dividend payout jobs | RQ queue + separate `rq worker` process | Run synchronously in-process, no worker needed |
| Players | Real player roster, admin-entered | Static sample roster (`app/data/demo_players.json`) -- real gamertags used as recognizable examples, but team/region are a rough snapshot that will drift out of date |
| Tournament results | Admin enters real results | Randomized automatically every few minutes (`app/services/demo_tournament_service.py`) |
| Bot trading population | Same bots, same code path | Identical -- no changes needed here |
| Accounts | Real signups | Anyone can register a real account against the local demo.db; there's also a seeded `demo-admin@forecast.local` login |

Everything else -- the order matching engine, wallet hold/release,
exact-conservation dividend math, quick-order pricing, auctions -- is
the identical code path as production. This isn't a mockup with fake
data bolted on; it's the real system with its two cloud dependencies
swapped out.

**Safety:** demo mode is controlled entirely by which `.env` file gets
loaded (`FORECAST_ENV_FILE=.env.demo` vs the default `.env`). The seed
script (`demo_seed.py`) refuses to run at all unless `DEMO_MODE=true` is
actually loaded, specifically so it can never accidentally seed fake
players/bots into the real production database.

## Running it

From `forecast-backend/`, with the venv active:

```bash
# 1. One-time (or whenever you want a clean slate): seed the demo database
python demo_seed.py            # top up an existing demo.db
python demo_seed.py --fresh    # wipe demo.db and start completely clean

# 2. Start the demo backend (a different port than the real one, 8001,
#    so you can run both side by side if you want)
FORECAST_ENV_FILE=.env.demo uvicorn app.main:app --reload --port 8001
# Windows PowerShell:
#   $env:FORECAST_ENV_FILE=".env.demo"; uvicorn app.main:app --reload --port 8001
```

From `Premium Esports Stock Market Front End/project/`:

```bash
npm run dev:demo   # Vite on port 5174, pointed at the demo backend via .env.demo
```

Open `http://localhost:5174`. Register any account (or log in as
`demo-admin@forecast.local` / `demo1234`), and you'll see the seeded
player roster already trading, bots posting orders every 15 seconds, and
a randomized tournament (with real dividend payouts) running roughly
every 3 minutes on its own -- nothing else to trigger by hand.

No `rq worker` terminal needed for demo mode -- dividend payouts run
in-process instead of going through a queue.

## Known simplifications (acceptable at demo scale, not correctness bugs)

- Two spots use `.with_for_update()` row locking
  (`app/services/wallet_service.py`, `app/services/position_service.py`).
  SQLite doesn't support that clause and SQLAlchemy silently no-ops it on
  that dialect -- SQLite's own file-level locking still keeps writes
  safe for a single local process, which is all demo mode ever is.
- Single process, single SQLite file -- fine for one person (or a small
  group) trying the demo; not something to scale up as-is.
- The static player roster (`app/data/demo_players.json`) is explicitly
  a point-in-time sample and will not track real roster changes over
  time -- that's fine, it's only there to make the demo market feel
  populated and recognizable.

## Files worth knowing about

- `app/core/config.py` -- `DEMO_MODE` / `FORECAST_ENV_FILE` / `DEMO_TOURNAMENT_INTERVAL_SECONDS`
- `app/db/types.py` -- the `GUID`/`JSONType` columns that make the same models work on both Postgres and SQLite
- `app/db/session.py` -- SQLite vs Postgres engine branching
- `app/services/local_pubsub.py` -- Redis-free live price feed
- `app/jobs/tasks.py` -- the `enqueue_*` functions branch to run synchronously in demo mode instead of going through RQ
- `app/services/demo_tournament_service.py` -- the randomized-tournament loop
- `app/data/demo_players.json` -- the static roster
- `demo_seed.py` -- the bootstrap script
- `.env.demo` (backend) / `.env.demo` (frontend) -- the two config files that turn this on
