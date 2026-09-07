# Forecast Backend -- Setup Guide

This is the backend for the Forecast fantasy Fortnite stock market:
users, wallets, tradeable player shares, a real order book (limit orders
+ quick buy/sell), tournament results, dividends, and a treasury
instrument. Everything that could be built without an actual running
database/Redis instance has been built and is sitting in this folder.
This guide is the rest: the accounts you need to create, and the exact
commands to run, to get it live.

Follow the steps in order. Every step says exactly what to click or
type. Total cost: **$0** while you're prototyping.

---

## 0. What's already done vs. what you need to do

**Done (in this folder):**
- Full database schema (users, wallets, players/shares, positions,
  orders, trades, tournaments, placement results, dividends, treasury,
  audit log, admin-tunable economic parameters)
- Order matching engine (real price/time-priority limit order book)
- Quick buy / quick sell (market order) pricing
- Dividend calculation + payout engine, using FIXED synthetic pools
  ($300k Cash Cup / $1.5M FNCS / $3M Global Championship) that match the
  validated economy simulation's locked-in numbers, instead of a
  real-world Fortnite prize pool
- A 0.25% transaction fee charged to the taker side of every trade fill
  (maker pays nothing), matching the simulation's locked-in tax rate
- Every new user automatically starts with $1,000,000 in fantasy cash at
  registration, matching the simulation's per-participant starting
  capital (self-serve deposits are gone -- `/wallet/deposit` is
  admin-only now, so the total money supply stays meaningful)
- Player-share IPO auction (admin opens a round, users pay a flat
  $10,000 entry fee to unlock bidding across every player, then bid cash
  toward whichever players they want; admin finalizes the round and
  shares are allocated pro-rata to bid size via exact largest-remainder
  apportionment, the same rounding method proven correct in the
  forecast_sim simulator, so total shares issued always conserves
  exactly -- no bidder is ever charged more than they explicitly bid,
  see `app/engine/auction_calculator.py`)
- Treasury instrument (purchase, daily accrual, redemption) defaulting
  to 1% APY, matching the simulation's cash treasury yield
- Manual admin tournament-result entry (+ dividend trigger)
- Bot/House liquidity provider
- REST API (FastAPI) covering all of the above
- WebSocket live price feed (Redis pub/sub)
- Background job queue (RQ) for dividend payouts and treasury accrual
- A full automated test suite for the money-math logic (already passing)
- A smoke-test script that exercises the entire system end-to-end

**You need to do (this guide, in order):**
1. Create a free Postgres database (Supabase)
2. Create a free Redis database (Upstash)
3. Install Python dependencies locally
4. Configure your `.env` file
5. Run the database migration
6. Run the smoke test to verify everything works
7. Create your first admin user
8. Run the API server + background worker
9. Try it

---

## 1. Create a free Postgres database (Supabase)

1. Go to **https://supabase.com/dashboard/new** and sign up (GitHub or
   email).
2. Click **New project**. Pick any name (e.g. `forecast`), generate a
   database password (click the dice icon), and save that password
   somewhere -- you'll need it in a minute. Pick any region close to you.
3. Wait ~2 minutes for the project to finish provisioning.
4. In the left sidebar, click the **Connect** button (or go to Project
   Settings -> Database).
5. Under **Connection string**, choose the **URI** tab, and copy it. It
   looks like:
   ```
   postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-xx-xxxx-1.pooler.supabase.com:6543/postgres
   ```
6. Replace `[YOUR-PASSWORD]` with the password from step 2, and change
   `postgresql://` to `postgresql+psycopg2://` at the very front (this
   tells SQLAlchemy which driver to use). Save this full string -- you'll
   paste it into `.env` in step 4.

**Free tier limits (current as of this writing):** 500 MB database, 2
active projects, and the project auto-pauses after 1 week of no activity
(just click "Restore" in the dashboard to unpause it -- your data isn't
lost). That's plenty for prototyping; you'll outgrow it only once you
have real users and real trade volume.

---

## 2. Create a free Redis database (Upstash)

Redis is used for: order-book pub/sub (live price updates) and the
background job queue (dividend payouts, treasury accrual).

1. Go to **https://console.upstash.com** and sign up.
2. Click **Create Database**. Pick any name, choose **Regional** (not
   Global -- Global is for multi-region, not needed here), pick a region
   close to your Supabase region, and select the **Free** plan.
3. Once created, open the database and find the **Redis Connect** /
   "TCP" connection string, which looks like:
   ```
   redis://default:xxxxxxxxxxxxxxxx@xxxxx-xxxx-12345.upstash.io:6379
   ```
   (Make sure you copy the `redis://` connection string, not the REST
   API URL -- this codebase talks to Redis directly, not through
   Upstash's REST API.)

**Free tier limits:** 256 MB data, 500,000 commands/month, 10 GB
bandwidth/month. This comfortably covers prototyping; each price update
and each background job is one Redis command, so 500K/month is a lot of
trading activity before you'd need to upgrade.

---

## 3. Install Python dependencies locally

Requires **Python 3.11+** installed on your machine.

```bash
cd forecast-backend
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

If you'd rather not sign up for Supabase/Upstash yet and just want to
try everything locally first, you can run Postgres + Redis on your own
machine instead with Docker Desktop installed:

```bash
docker compose up -d
```

That starts a local Postgres and local Redis matching the defaults
already in `.env.example`, so you can do everything below without any
cloud signup, then switch to Supabase/Upstash later just by changing two
lines in `.env`.

---

## 4. Configure your `.env` file

```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in:

- `DATABASE_URL` -- the Supabase connection string from step 1 (or leave
  the default if you're using `docker compose up -d` from step 3)
- `REDIS_URL` -- the Upstash connection string from step 2 (or leave the
  default if using Docker)
- `JWT_SECRET_KEY` -- generate a real one:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
  paste the output in as the value.

Everything else in `.env.example` has a sensible default and can be left
alone for now.

---

## 5. Run the database migration

This creates every table in your Postgres database.

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

If this fails with a connection error, double check `DATABASE_URL` in
`.env` -- almost always the cause is a typo'd password or an unpaused
Supabase project.

---

## 6. Run the smoke test

This is the most important step: it proves the whole system actually
works against your real database -- deposits, order matching, quick
buy/sell, tournament results, dividend payouts, and treasury
purchase/accrual/redemption, with every dollar and every share checked
to the penny.

```bash
python3 scripts/smoke_test.py
```

You should see a long list of `[PASS]` lines and, at the end, `All NN
checks passed.` If anything fails, the error message tells you exactly
which check and what it found -- that's a real bug, not a formatting
issue, so it's worth reporting back before moving on.

You can also run just the pure business-logic unit tests (no database
needed, runs in milliseconds):

```bash
python3 -m unittest discover -s tests -v
```

---

## 7. Create your first admin user

Admin rights (creating players/IPOs, entering tournament results,
changing the treasury rate or other economic parameters) can only be
granted by directly editing the database -- there's no API endpoint for
it on purpose, since an endpoint that grants admin rights would itself
need to be protected by... an admin.

1. Start the API server (see step 8 below), then register a normal
   account through it:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email": "you@example.com", "password": "a-real-password", "display_name": "You"}'
   ```
2. Promote that account to admin:
   ```bash
   python3 scripts/make_admin.py you@example.com
   ```
3. Log in again (`POST /api/v1/auth/login`) to get a fresh token -- your
   old token doesn't know about the new role until you log in again.

---

## 8. Run the API server + background worker

You need **two processes** running at the same time (in two terminal
tabs):

**Terminal 1 -- the API server:**
```bash
uvicorn app.main:app --reload
```
This serves the REST API and the WebSocket price feed at
`http://localhost:8000`.

**Terminal 2 -- the background worker:**

On macOS/Linux:
```bash
rq worker forecast-default --url redis://localhost:6379/0
```

**On Windows**, RQ's default worker doesn't work at all -- RQ's own docs
say so directly ("not possible to run the workers on Windows without
using WSL"). Two Windows-specific problems stack on top of each other:

1. The plain `rq worker` command crashes immediately with
   `AttributeError: module 'os' has no attribute 'fork'` -- Windows has
   no `os.fork()`, which RQ's default worker relies on to run each job in
   a forked subprocess. `SimpleWorker` fixes this by running jobs
   in-process instead of forking.
2. `SimpleWorker` on its own still crashes on the *first job it tries to
   run*, with `AttributeError: module 'signal' has no attribute
   'SIGALRM'`. That's because RQ enforces per-job timeouts by arming
   `signal.SIGALRM`, which -- like `os.fork()` -- doesn't exist on
   Windows.

Rather than chase RQ's CLI flags for this, use the small wrapper script
in this repo that runs `SimpleWorker` with job-timeout enforcement
disabled (`app/jobs/windows_worker.py`):

```bash
cd forecast-backend
python -m app.jobs.windows_worker
```

It reads `REDIS_URL` the same way the rest of the app does (via
`app/core/config.py` / your `.env`), so there's nothing extra to pass on
the command line. This is what actually processes dividend payouts after
an admin finalizes a tournament -- without this running, finalizing a
tournament will queue the payout but it'll just sit there unprocessed.

**Optional -- daily treasury interest accrual.** Nothing runs this
automatically yet; the simplest way to trigger it once a day is a cron
job that enqueues the job:
```bash
# crontab -e, then add:
0 3 * * * cd /path/to/forecast-backend && venv/bin/python3 -c "from app.jobs.tasks import enqueue_treasury_accrual; enqueue_treasury_accrual()"
```

---

## 9. Try it

With both processes running, open **http://localhost:8000/docs** in
your browser -- FastAPI auto-generates a full interactive API explorer
where you can try every endpoint (register, deposit, IPO a player,
place orders, enter tournament results, etc.) by clicking "Try it out".

A quick end-to-end path to try by hand:
1. `POST /api/v1/auth/register` -- create a user. This automatically
   credits a $1,000,000 starting balance (admin-tunable via
   `wallet.starting_balance`, see "Every economic formula is adjustable"
   below) -- no separate deposit step needed.
2. `POST /api/v1/auth/login` -- get a token, click the padlock icon in
   `/docs` and paste it in as `Bearer <token>`
3. As your admin account: `POST /api/v1/players` -- IPO a player (this
   automatically seeds House bot liquidity so it's immediately
   tradeable). Optionally, instead of (or before) letting people quick-buy
   it from bot liquidity, run it through an auction: as admin,
   `POST /api/v1/admin/auctions` to open a round; as any user,
   `POST /api/v1/auctions/{round_id}/join` (pays the $10,000 entry fee),
   then `POST /api/v1/auctions/{round_id}/bids` with `{"player_id": ...,
   "bid_amount": ...}` for each player they want; as admin,
   `POST /api/v1/admin/auctions/{round_id}/finalize` to allocate shares
   and settle cash for every player that received a bid.
4. `POST /api/v1/orders/quick` -- quick-buy some shares. A 0.25%
   transaction fee is charged to whichever side is the taker (see
   `fees.transaction_fee_pct`) -- the maker side pays nothing.
5. As admin: `POST /api/v1/admin/tournaments`, then
   `POST /api/v1/admin/tournaments/{id}/results`, then
   `POST /api/v1/admin/tournaments/{id}/finalize` -- watch the dividend
   land in your wallet a few seconds later (once the RQ worker picks it
   up). Cash Cup / FNCS / Global Championship tournaments pay out of a
   fixed synthetic pool ($300k / $1.5M / $3M by default) instead of a
   real-world prize pool unless you enter an exact `prize_won` -- see
   `dividend.cash_cup_pool` / `dividend.fncs_pool` / `dividend.global_pool`.
6. Connect a WebSocket client to `ws://localhost:8000/api/v1/ws/prices/{player_id}`
   and place another trade in a second tab -- you'll see the price push
   through live.

Need more fantasy cash for a test account beyond the automatic starting
balance? `POST /api/v1/wallet/deposit` is admin-only now (pass
`{"amount": ..., "user_id": "<target user id, optional>"}` as your admin
account) -- it's no longer self-serve, so the total money supply stays
meaningful against the validated economy simulation.

---

## Bot trading population

A background loop (started automatically when `uvicorn` starts, see the
`lifespan` in `app/main.py`) keeps a population of bot trader accounts
placing buy/sell orders so the market has real activity even with a
small human user base -- see `app/services/bot_trading_service.py` for
the full design and exactly which of the validated simulator's trading
archetypes were ported (several were dropped or simplified because they
depend on systems, like a synthetic news/rumor feed, that don't exist in
this backend).

- **New table**: this adds `bot_profiles` to the schema. If you already
  ran the migration in section 5 before this was added, generate and
  apply a new one: `alembic revision --autogenerate -m "add bot_profiles"`
  then `alembic upgrade head`.
- **Controlled by**: `BOT_TRADING_ENABLED` / `BOT_TICK_INTERVAL_SECONDS`
  in `.env` (restart required to change), and the `bots.*` keys in
  `GET/POST /api/v1/admin/economic-parameters` (population size,
  participation rate, order sizing, limit-vs-quick mix -- takes effect on
  the very next tick, no restart).
- **Manual control**: `POST /api/v1/admin/bots/seed` tops the population
  up immediately instead of waiting for the next tick; `POST
  /api/v1/admin/bots/tick` runs one tick on demand (useful for testing).
- Bot accounts are ordinary `User` rows (real wallets, real positions,
  same starting balance as a human signup) tagged by a `BotProfile` row
  -- they're excluded from the leaderboard but otherwise indistinguishable
  from a human account in the data model. `Order.is_bot` / `Trade.buyer_is_bot`
  / `Trade.seller_is_bot` mark which side of a fill was a bot, for
  analytics.
- **Known limitation**: bot orders never expire. A resting order that
  never fills sits there forever (this is intentional -- a market with
  zero unfilled orders doesn't look real), but it also means a bot's
  cash/shares can gradually get tied up over many ticks. The
  `liquidity_provider` archetype self-corrects (cancels and re-quotes
  every tick), the directional archetypes do not. An order-expiry sweep
  would be the natural follow-up if bots start going quiet.

---

## Every economic formula is adjustable without touching code

This was a specific requirement, so it's worth spelling out exactly
where and how:

**Via the admin API, no deploy needed:**
- `GET/POST /api/v1/admin/economic-parameters` -- quick buy/sell
  slippage steepness (`quick_trade.market_impact_coefficient`),
  synthetic liquidity depth (`quick_trade.synthetic_depth_fraction`,
  `quick_trade.synthetic_depth_min`), the dividend platform fee
  (`dividend.platform_fee_pct`), the House bot market-maker's ladder
  shape (`bot_liquidity.num_levels`, `.step_pct`, `.spread_pct`,
  `.qty_per_level`), the per-trade transaction fee
  (`fees.transaction_fee_pct`, default 0.25%, taker pays), the flat
  auction entry fee (`auction.entry_fee`, default $10,000 -- see
  `POST /api/v1/admin/auctions` below), the fixed synthetic dividend pools for Cash Cup / FNCS / Global
  Championship tournaments (`dividend.cash_cup_pool`,
  `dividend.fncs_pool`, `dividend.global_pool` -- default $300k / $1.5M /
  $3M), and every new user's automatic starting balance
  (`wallet.starting_balance`, default $1,000,000). Change any of these
  and the very next order/payout/registration uses the new value -- see
  `app/services/economic_params_service.py` for the full list and what
  each one controls.
- `GET/POST /api/v1/admin/dividend-curve` -- the placement -> percent
  of prize pool payout curve used whenever an admin enters a placement
  without an exact dollar amount.
- `POST /api/v1/admin/treasury/rate` -- the treasury instrument's APY.
  Old holdings keep accruing at whatever rate was active when purchased
  (like a real bond series); new purchases get the new rate.

**In code (the formulas themselves, not the numbers):**
- `app/engine/quick_trade_pricing.py` -- how quick buy/sell walks the
  order book and prices the synthetic remainder
- `app/engine/dividend_calculator.py` -- how a placement becomes a
  dollar pool, and how that pool splits across shareholders
- `app/engine/treasury_calculator.py` -- how interest accrues
- `app/services/market_maker_service.py` -- the House bot's quoting
  strategy

Every one of those files has a `PLACEHOLDER FORMULA` docstring at the
top explaining exactly what standard/defensible default was chosen and
why, specifically so it's easy to find and replace once your simulation
phase tells you what the real numbers/formulas should be.

---

## What's NOT done -- read this before you rely on this in production

This is a v1 built to be correct and testable, not yet production-hardened:

- **Auctions are opt-in, not automatic.** Creating a player (`POST
  /api/v1/players`) still defaults to the House owning 100% of its
  shares, tradeable immediately via bot liquidity -- nothing forces every
  new player through an auction. Running `POST /api/v1/admin/auctions` +
  bidding + `POST /api/v1/admin/auctions/{id}/finalize` right after IPO'ing
  a fresh batch of players is how you reproduce the simulation's
  chapter-start distribution; it's a manual admin workflow for now, not
  wired to run automatically whenever a player is created.
- **Auction round covers whatever players get bid on, not a curated
  set.** There's no "add these N players to this round" step -- any
  active player can receive a bid once a round is open, and
  `finalize_round` settles every player that received at least one bid.
  If you want a clean "auction exactly these players" workflow, filter
  which players you IPO before opening the round.
- **No automated tournament data ingestion.** Confirmed while building
  this: there is no free, documented public API for official Fortnite
  competitive results. Epic's own competitive site
  (competitive.fortnite.com) has no public API, and the free
  "Fortnite-API" services only cover cosmetics and casual battle-royale
  stats, not Cash Cup/FNCS placements. Results have to be entered by an
  admin (or bulk-imported via a CSV you build yourself) through the
  admin API. `Tournament.result_source` exists specifically so an
  automated importer (a scraper, or a paid tracker API like Osirion or
  Fortnite Tracker Network, if you ever want to pay for one) can be
  added later without changing anything else.
- **Single-process order book.** The live order book is held in this
  process's memory (rebuilt from the database on startup) and guarded
  by an in-process lock. This is correct for one API server process, but
  the roadmap's mention of "Redis for order-book state" is specifically
  about supporting *multiple* API processes/machines sharing one
  consistent book -- that migration hasn't been done. Don't run more
  than one `uvicorn` worker process against the same database yet.
- **Dividend record-date gap.** Shareholders are snapshotted at the
  moment the background job actually runs, not the moment the admin
  finalized the tournament. For prompt processing (seconds to minutes)
  this is a fine approximation; it is not immune to someone buying
  shares in that gap specifically to catch a dividend.
- **House account can be undercapitalized.** The House is seeded with
  $10,000,000 in cash and 100% of every player's shares at IPO, and acts
  as buyer/seller of last resort for quick orders and bot liquidity. If
  trading volume is lopsided enough, the House's cash or share inventory
  for a given player could theoretically run out or go negative (this
  would surface as a database constraint error, not a silent bug). Real
  money would need a proper risk/inventory model here; for prototyping,
  just keep an eye on the House's wallet via the API.
- **Bot market maker is intentionally simple.** It posts a static
  ladder around the last price and doesn't react to inventory, time, or
  volatility. Fine for making sure every player has *some* liquidity;
  not a realistic market maker.
- **No rate limiting, no email verification, no password reset flow, no
  production logging/monitoring.** All standard things a real launch
  needs that weren't in scope for "backend and data."
