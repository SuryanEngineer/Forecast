# Forecast — Project Status & Roadmap

**Last updated:** August 4, 2026
**Purpose of this file:** one place to see the whole project's state — what's built, what's verified working, what's known-broken, and what's left — without having to reconstruct it from chat history. Update this whenever a phase of work wraps up.

---

## 1. What Forecast is

A fantasy stock market for competitive Fortnite: users get fantasy cash, "IPO" pro players as tradeable stocks, trade shares on a real order book, and earn dividends when their players place well in tournaments (Cash Cups, FNCS, Global Championship). The economics (fees, dividend pools, treasury yield, starting balances) were validated in a standalone Python simulation before any of it was built for real, specifically so the numbers wouldn't need to change later.

## 2. The three (four) pieces of this project

1. **Economy simulator** (`forecast_sim`) — Python, validates the economics via bulk simulated runs (bot/human population, trading strategies, tournament cycles, metrics like Gini coefficient and turnover). Not a running product; a design/validation tool. Its output is a locked set of numbers (fees, pools, rates) that everything else must match.
2. **Backend** (`forecast-backend/`) — FastAPI + Postgres + Redis. The real, live product API: auth, wallets, order matching, dividends, treasury, auctions, bot trading, admin tools.
3. **Frontend** (`Premium Esports Stock Market Front End/project/`) — React/Vite, a Figma Make export wired to the real backend. The actual app a user opens in a browser.
4. **Infrastructure** — Supabase (Postgres), Upstash (Redis), both free-tier, both live and working as of this session.

---

## 3. Current status by component

### 3.1 Economy simulator — validated, but **not safely stored** (action needed, see §6)

Fully built and validated across multiple iterations: human/bot population split, tournament tiers, ELO, seasonal points, expanded metrics, a success-criteria evaluator, a parameter-sweep runner, and a 100-run batch analysis confirming bot/human behavioral symmetry holds. Final locked-in economics: flat $10k auction entry fee, 0.25% transaction fee, ~1%/year cash treasury yield, fixed dividend pools ($300k Cash Cup / $1.5M FNCS / $3M Global), $1M starting balance per user.

**Problem:** this code currently only exists in ephemeral session/build directories, not in this `Forecast` folder or anywhere else under your control. If a past delivered zip of it isn't saved somewhere on your machine already, **the validated simulator source could be lost.** See §6, item 1 — this needs to be resolved soon.

### 3.2 Backend (`forecast-backend/`) — live, connected to real infrastructure, verified end-to-end

**Confirmed working against your real Supabase + Upstash tonight** (not just unit tests): registration with real starting balance, deposits, limit order placement and matching, order holds/releases, taker-pays transaction fees, dividend payouts from tournament finalization, the fixed Cash Cup pool, a full player-share auction round (join, bid, finalize, largest-remainder share allocation, "never overcharge" guarantee), treasury purchase/accrual/redemption at the correct 1% APY, and the admin-tunable quick-trade slippage parameter taking effect live.

Subsystems built this project:
- Auth, wallets, positions, order matching engine (limit + quick/market orders), price snapshots, WebSocket price push
- Dividend engine (placement-curve payouts + fixed synthetic pools for Cash Cup/FNCS/Global)
- Treasury (cash yield instrument, admin-adjustable rate)
- Auction/IPO subsystem (flat entry fee, exact largest-remainder share allocation, hard "never charge more than the bid" guarantee)
- Market data, leaderboard, and position-listing endpoints (built specifically to give the frontend something real to render)
- **Bot trading population** (new this session) — 10 trading archetypes ported from the simulator's validated logic (scaled back to only what has real live data behind it — no fake rumor/news signals), running automatically in the background every 20 seconds, fully admin-tunable without a redeploy

Bugs found and fixed this session (all via live testing against real infra, not guesswork):
- Every native Postgres enum column across 8 model files was silently storing uppercase Python enum names instead of the lowercase values the rest of the app expects — blocked the very first schema migration. Fixed + verified.
- Missing 204-response `response_model=None` on the auction bid-cancel endpoint — blocked the very first server startup. Fixed.
- **Quick-buy could crash with a raw 500** whenever a player's House share inventory got fully depleted, because the synthetic liquidity fallback never checked real inventory before "selling" shares that didn't exist. Fixed at the engine level with 5 new regression tests, all passing.
- Stale `.env` value (`DEFAULT_TREASURY_ANNUAL_RATE=0.04`) from before this session's economics reconciliation, causing treasury redemptions to pay 4% instead of the locked-in 1%. Fixed.
- `bcrypt`/`passlib` version-mismatch warning cluttering every run. Pinned, cosmetic-only.

**Known limitations (by design, not bugs):**
- Auctions are opt-in/manual, not triggered automatically when a player is created.
- No automated tournament results ingestion — confirmed there's no free public API for competitive Fortnite results (Epic has none; free "Fortnite-API" services only cover cosmetics/casual stats). Results are admin-entered. See §6, item 2.
- Single-process order book (in-memory, rebuilt from DB on startup) — fine for one `uvicorn` process, not yet safe to run multiple API server processes against the same database.
- Bot orders never expire — intentional (a market with zero unfilled orders doesn't look real), but means a directional bot's cash/shares can gradually get tied up over many ticks. The market-maker bot archetype self-corrects by re-quoting each tick; the others don't yet.
- Dividend "record date" is whenever the background job actually runs, not the exact moment of tournament finalization — a small timing gap, not a correctness bug at current scale.

### 3.3 Frontend (`Premium Esports Stock Market Front End/project/`) — running, wired to the real backend, lightly live-tested

Rewired this session from a raw Figma Make export (mock data) to the real backend: auth flow, sidebar, dashboard, markets list, player trade modal (limit + quick orders), portfolio, leaderboard, tournaments. `npm install` and `npm run dev` both confirmed working on your machine tonight (Vite serving on `localhost:5173`) — this was the first time this frontend had ever actually been built or run anywhere.

Verified live tonight: registration, login, limit buy/sell orders. Quick-buy was broken (see backend section above, now fixed — needs a re-test). Cosmetic fields with no backend data source were deliberately dropped rather than faked: team colors, nationality, age, bio, ELO, consistency score, achievements. `InvestorModal.tsx` and `PlayerProfile.tsx` are still orphaned (not wired to anything, harmless).

**Not yet done:** a real production build (`npm run build`) has never been tried, only the dev server. Also worth a pass at some point: the 2 high-severity `npm audit` findings and the blocked `esbuild`/`@tailwindcss/oxide` postinstall scripts (dev server works fine without them, but worth understanding before deploying anywhere real).

### 3.4 Infrastructure — live and confirmed

- **Supabase (Postgres)**: live, schema migrated, password rotated off the originally-leaked one.
- **Upstash (Redis)**: live, TLS working, password rotated off the originally-leaked one.
- **`.env.example`**: cleaned up to use obvious placeholders instead of real (leaked) values, and documents the two gotchas that cost real time tonight — Supabase's IPv6-only direct connection, and Upstash requiring `rediss://`.
- **No version control** on this project folder currently (confirmed no `.git` anywhere under `Forecast/`). See §6, item 3.

---

## 4. What's left to do

### Immediate (next session)
1. Re-verify quick-buy works now against your live backend (restart `uvicorn`, try a quick-buy in the browser).
2. Watch a few bot tick cycles in the `uvicorn` terminal to confirm the bot population is trading without errors.
3. Run `alembic revision --autogenerate` + `alembic upgrade head` if you haven't yet since the `bot_profiles` table was added.
4. **Start the `rq worker` process** (`rq worker forecast-default --url <your REDIS_URL>`) — confirmed not yet running this session. Without it, dividend payouts queued by `POST /admin/tournaments/{id}/finalize` sit in Redis forever and never actually pay out. The smoke test doesn't catch this because it calls the payout logic directly, bypassing the queue entirely. This needs a third always-running process alongside `uvicorn` and the frontend dev server.

### Short-term
4. Order-expiry sweep for bot (and possibly human) resting orders, so bots don't gradually lock up all their cash in stale limit orders.
5. A real `npm run build` pass on the frontend, plus a look at the audit warnings, before this goes anywhere beyond your own machine.
6. Decide on the real Fortnite data question (see §6, item 2) and act on it.
7. Get the simulator source safely into version control (see §6, item 1) before it's at risk of being lost for good.

### Medium-term
8. Multi-process order book support (Redis-backed instead of in-process) if/when you need more than one API server.
9. Automatic (not manual/admin-triggered) auction flow when a player is created, if that's the experience you want.
10. Tighten the dividend record-date timing if it ever matters at your scale.

### Needs scoping / your input first
11. What "real Fortnite data" should actually mean for v1 given no free API exists (see §6, item 2).
12. Whether/how to deploy this beyond your own machine (hosting for the backend + frontend, not just the free-tier DB/Redis).

---

## 5. Open decisions needing your input

1. **Simulator source is at risk.** Do you have a saved copy of the delivered simulator code (zip) anywhere outside this session? If not, I should help you get a copy safely into this `Forecast` folder (or wherever you want the canonical copy) before it's lost. This should probably happen soon.
2. **Real Fortnite data**, given no free public API exists for competitive results:
   - Keep manual admin entry (works today, zero cost, more your time)
   - Look into paid tracker APIs (Osirion, Fortnite Tracker Network) — I haven't researched current pricing/coverage for either yet
   - Some hybrid (manual entry now, revisit a paid API once the user base justifies the cost)
3. **Version control.** This project has no git repository anywhere on your machine right now. Want me to set one up (with a `.gitignore` that correctly excludes `.env`, `node_modules`, `venv`, `__pycache__`) so you have real history and can safely experiment? I'd want to confirm where you want it hosted (just local, or pushed to a private GitHub repo) before doing anything, since that's a bigger decision than editing code.
4. **Deployment target.** Everything currently runs on your own machine (`localhost`). If/when you want other people to actually use this, the backend and frontend both need real hosting (separate from the already-live Supabase/Upstash) — worth a dedicated conversation when you're ready, not something to decide now.
