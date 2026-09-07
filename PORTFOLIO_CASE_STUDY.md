# Forecast — Full Project Overview & Portfolio Guide

This is a working document for turning Forecast into strong portfolio material: a complete project overview, the engineering stories worth telling, and concrete ideas for how to present it. Pull whatever's useful into your actual portfolio site, resume, or GitHub README — this file itself is meant for you, not necessarily to be published as-is.

---

## Part 1: What the project is

**Forecast** is a fantasy stock market for competitive Fortnite esports. Users get fantasy cash, "IPO" professional players as tradeable stocks, trade shares against a real order-matching engine, and earn dividends when their players place well in tournaments (Cash Cups, FNCS qualifiers/finals, the Global Championship).

What makes it more than "a trading app skin over a database" is the order the work happened in. Before any product code existed, the underlying economics — transaction fees, dividend pool sizes, treasury interest, starting capital, how liquidity should behave — were validated in a standalone economic simulation, run in batches, measured, and only locked in once the numbers behaved. The live backend and frontend were then built to match those validated numbers exactly, not the other way around.

The project has three parts:

1. **`forecast_sim`** — a Python economic simulator. Not a running service; a research/validation tool.
2. **`forecast-backend`** — a FastAPI + PostgreSQL + Redis backend. The real, live product API.
3. **The frontend** — a React/Vite/TypeScript SPA wired to the real backend.

---

## Part 2: Architecture deep dive

### 2.1 The simulator (`forecast_sim`)

A population of simulated traders (hundreds of agents, human and bot, deliberately given *identical* trading logic after an early version found and removed an unrealistic asymmetry between them) trade against each other across simulated Fortnite chapters — tournaments happen, players' prices move, dividends get paid, a cash treasury accrues interest. Each agent follows one of 15 trading-strategy archetypes (momentum trading, contrarian, value investing, panic selling, market making, dividend hunting, and more), each with its own target-selection logic and risk profile.

The simulator was run in batches of 100+ full simulated "chapters" at a time, each producing metrics like:
- Wealth distribution (Gini coefficient) — is the platform accidentally creating extreme inequality?
- Turnover and liquidity health — is the market actually tradeable, or does it seize up?
- Bot vs. human behavioral symmetry — do bots and humans converge to similar outcomes, or does one group systematically win?
- Cash-to-holdings ratio, passive-holder percentage, bank liquidity trend over time

A dedicated success-criteria module scored each run pass/fail against target ranges, and a parameter-sweep runner could vary knobs (fee rates, pool sizes, participation rates) across many runs to find stable, healthy configurations before anything got built for real.

**This is the part of the project most worth talking about in an interview.** It's the difference between "I built a trading app" and "I designed and validated an economic system, then built the product to match."

### 2.2 The backend (`forecast-backend`)

A layered FastAPI application:

```
app/
  api/v1/       -- HTTP route handlers (thin: validate → call service → commit)
  services/     -- business logic (auth, wallet, orders, dividends, treasury, auctions, bots)
  engine/       -- pure, dependency-free logic (order matching, pricing, apportionment math)
  models/       -- SQLAlchemy ORM models
  schemas/      -- Pydantic request/response contracts
  jobs/         -- Redis Queue (RQ) background job definitions
```

The `engine/` layer is deliberately kept free of any database or web-framework dependency — it's pure functions and dataclasses. That's what made it possible to unit-test the order-matching engine, the dividend apportionment math, the auction settlement math, and the quick-trade pricing formula in complete isolation, including a randomized property-style test that sweeps hundreds of random inputs checking a hard invariant ("no auction bidder is ever charged more than their bid") rather than just a handful of fixed examples.

**Subsystems built:**
- **Auth & wallets** — JWT auth, a wallet model with a `hold → debit/credit → release` pattern so cash reserved against an open order can never be double-spent or silently lost, backed by an append-only ledger for a full audit trail.
- **Order matching** — real price-time-priority matching, resting limit orders, partial fills, and a "quick order" (market order) path that sweeps the book and falls back to synthetic house liquidity, with slippage that scales with order size.
- **Dividends** — tournament placements translate into per-share payouts via an exact largest-remainder ("Hamilton") apportionment algorithm — the same method used in real-world proportional-representation voting systems — so a fixed prize pool distributes to shareholders without leaking or duplicating a single cent to rounding.
- **Treasury** — a cash-yield instrument users can buy into, accruing interest at an admin-adjustable rate.
- **Auctions** — a full player-share IPO mechanism: flat entry fee, per-player bidding, and settlement via the same exact apportionment method, with a hard, tested guarantee that no bidder is ever charged more than they bid.
- **Bot trading population** — a background-scheduled population of bot accounts trading through the *exact same* order-placement code a human's browser click uses (no privileged internal shortcut), running 10 strategy archetypes adapted from the validated simulator, fully tunable via a live admin API without a redeploy.
- **Admin tooling** — every economic parameter (fees, slippage, dividend pool sizes, bot behavior) lives in the database and is adjustable through an authenticated admin API at runtime, not hardcoded.

### 2.3 The frontend

A React 18 + TypeScript + Vite app (Tailwind v4, shadcn/ui, Recharts), originally scaffolded from a Figma Make export as static mock data and rewired end-to-end to the real backend: a real auth flow, live market data, a trading modal supporting both limit and quick orders, portfolio valuation computed from real positions and live prices, a leaderboard, and tournament results — with a deliberate, documented decision to drop cosmetic fields (team colors, bios, ELO, achievements) that had no real backend data source rather than fake them.

---

## Part 3: Engineering stories worth telling

These are the moments in this project that make for genuinely good interview answers — each one is a real bug or design problem, not a hypothetical.

**"Tell me about a subtle bug you found and fixed."**
Every native PostgreSQL enum column across 8 different model files was silently storing the *uppercase Python enum name* (`LIMIT`) instead of the *lowercase value* (`limit`) the rest of the app — including hand-written SQL CHECK constraints — expected, because SQLAlchemy's `Enum` type defaults to using `.name`, not `.value`, unless told otherwise. It never surfaced until the very first real database migration ever ran, because every prior test had exercised the Python-level enum, not what actually got persisted. Root-caused it, fixed all 12 occurrences across the codebase in one pass, and it's exactly the kind of bug that's invisible until you actually run something against a real database rather than mocks.

**"Tell me about a production-safety bug you caught before it caused real damage."**
A "quick buy" market order could fall back to synthetic liquidity from a house account without ever checking whether the house actually still owned enough real shares of that specific player to sell — meaning enough trading volume could push a share count negative, which the database's own conservation constraint would then reject as a raw, unhandled crash deep in a settlement path. Traced it from a live 500 error back through to the actual architectural gap, fixed it by threading a hard inventory cap through the pricing engine, and wrote 5 new regression tests specifically encoding the fix as a guaranteed property rather than a one-off patch.

**"Tell me about validating your own work rigorously."**
Wrote a smoke test that exercises the entire live stack — registration, deposits, order matching, fee collection, dividend payouts, a full auction round, treasury accrual and redemption — against a real Postgres/Redis instance, not mocks, with hand-computed expected values asserted to the cent (e.g., asserting a specific auction bidder's shares-won, amount-charged, and final cash balance down to the exact cent after a deliberately non-evenly-divisible bid scenario). Caught a real false-positive-test bug in this suite before it shipped: a negative test whose own assertion could have been silently swallowed by an overly broad `except Exception`, refactored to make the check unambiguous.

**"Tell me about debugging real infrastructure, not just code."**
A live-testing session surfaced a chain of real infra issues in one sitting: a Supabase free-tier project auto-paused after inactivity (diagnosed via a TCP-level port test to distinguish "refused" from "auth failure"), Upstash requiring a `rediss://` TLS scheme that a plain `redis://` string silently failed against, a stale local `DEFAULT_TREASURY_ANNUAL_RATE` config value producing a subtly wrong interest calculation, and a FastAPI startup crash from a missing `response_model=None` on a 204 endpoint. Each diagnosed methodically from symptom to root cause rather than guessed at.

---

## Part 4: Tech stack summary

**Backend:** Python, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Redis (pub/sub + RQ background jobs), JWT auth, WebSockets, `unittest`.
**Frontend:** React 18, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix primitives), Recharts.
**Infrastructure:** Supabase (managed Postgres), Upstash (managed Redis), both free-tier.
**Simulation:** Python, NumPy — Monte Carlo-style batch simulation with custom metrics and success-criteria evaluation.

---

## Part 5: What sets this apart from a typical portfolio project

Most portfolio trading/marketplace apps are CRUD with a veneer of "trading" on top — create a listing, buy it, done. Forecast has a few things that specifically read as "this person thinks like an engineer building a real financial-ish system," which is worth being explicit about because it's easy to undersell in a README:

- **Conservation is provable, not just tested.** Share counts and cash are designed to sum correctly by construction (exact apportionment math), backed up by database constraints as a second line of defense, not just application-layer checks that could be bypassed by a bug elsewhere.
- **The economics were designed before the product, with data.** Most projects pick numbers (a 1% fee, a $10k entry cost) and hope. This project ran the numbers through a simulator first.
- **Real infrastructure, real failure modes.** It's easy to build something that only ever ran against `localhost` and a developer's imagination. This project has a real paper trail of debugging real managed-service quirks (Supabase, Upstash) under time pressure.
- **A background agent population that doesn't cheat.** The bot traders use the identical code path and validation a human uses — no `if is_bot: skip_checks()` shortcut anywhere. That's a deliberate design choice worth calling out, because it's the kind of thing that's tempting to skip and easy to regret later.

---

## Part 6: Ideas for your portfolio page

### Suggested page structure

1. **One-line hook** at the top — something like: *"A fantasy stock market for competitive Fortnite, where the economics were validated in a custom Monte Carlo simulation before a single line of the live product was written."* Leads with what's actually differentiated, not the tech stack.
2. **3–4 short highlight bullets** (skimmable — most viewers won't read prose): simulation-validated economics, exact-conservation financial math, real order-matching engine, bot population trading through production code paths.
3. **Screenshots / short demo GIF** — the trading modal mid-trade and the dashboard are probably your best static shots; a 10–15 second screen recording of registering → buying → seeing a live price update over the WebSocket would be a strong, short demo if you're willing to record one.
4. **Architecture diagram** — see below, I can generate one directly as an embeddable image.
5. **"Engineering highlights" section** — pull 2–3 of the stories from Part 3 above, written tight (3–4 sentences each: the problem, why it was subtle, how you found and fixed it).
6. **Tech stack row** (icons/badges are fine here, this is the one place skimming is expected).
7. **Links**: live demo (if you deploy it — see §36 in `PROJECT_STATUS.md`), GitHub repo (tagged release, not a moving `main` branch — see the git instructions from earlier), and optionally the simulator's own README (it's genuinely detailed and worth linking separately if you're proud of the validation work).

### Resume bullet point ideas (tight, quantified, pick 2–3)

- *Designed and validated a virtual economy's fee structure, dividend pools, and liquidity rules using a custom Python Monte Carlo simulation (100+ batch runs, Gini coefficient / turnover / behavioral-symmetry metrics) before implementing the production system.*
- *Built a FastAPI + PostgreSQL trading backend with an exact-conservation financial ledger, a price-time-priority order-matching engine, and a largest-remainder apportionment algorithm guaranteeing dividend/auction payouts never leak or duplicate a cent.*
- *Diagnosed and fixed a production data-integrity bug in a synthetic liquidity fallback that could push share inventory negative under load, closing the gap with a hard inventory cap and 5 new regression tests.*
- *Implemented an autonomous trading-bot population (10 strategy archetypes) that transacts through the same validated, safety-checked code path as real users, tunable live via an admin API with zero downtime.*

### Interview talking-point outline ("tell me about a project you're proud of")

1. What it is, in one sentence (the hook above).
2. Why you built the simulator first — the *reasoning*, not just that you did it (validating fee/dividend/liquidity assumptions is expensive to get wrong after users have real money in the system).
3. One specific engineering story from Part 3, told as: symptom → your diagnostic process → root cause → fix → how you verified it stayed fixed (tests).
4. What you'd do differently / what's still open (order expiry for bot orders, multi-process order book, real tournament data ingestion — see `PROJECT_STATUS.md` §3–4). Showing you know what's *not* done, and why, reads as more senior than pretending it's finished.

### Things that would meaningfully strengthen this before/after publishing

Roughly in order of effort-to-impact:

1. **A tagged GitHub release** (already covered in the instructions from earlier) — link to that, not a moving branch.
2. **An architecture diagram image** — see below, this is cheap and high-value.
3. **A short demo GIF or video** — even 10-15 seconds of the real app running is worth more than any amount of description.
4. **A live deployed version** — the single highest-impact addition if you're willing to do it; a link a recruiter can actually click and use beats a screenshot every time. `PROJECT_STATUS.md` §4 has the deployment checklist.
5. **A CI badge / test-passing badge** on the GitHub README — cheap to set up (GitHub Actions running the existing `unittest` suite on push), and it's a strong, quiet signal of engineering discipline.
6. **A short "Engineering Decisions" doc** — you already effectively have the content for this in Part 3 above; formatting it as a standalone `ENGINEERING.md` in the repo (separate from the more operational `PROJECT_STATUS.md`) gives technical interviewers something meaty to read if they click through.
