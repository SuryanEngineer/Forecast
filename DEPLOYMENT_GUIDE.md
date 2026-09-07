# Deploying Forecast as a real, live website

This is the exact, step-by-step path from "runs on my computer" to "a real
URL anyone can sign up on," using entirely free services. Follow it in
order the first time; after that, most of it (steps 1–4) is one-time
setup and you'll only ever touch steps 6–8 again.

**What you'll end up with:**
- A live backend API, always reachable at a URL like
  `https://forecast-backend.onrender.com`
- A live frontend website at a URL like
  `https://forecast-frontend.onrender.com` — this is the link you give
  out to real users
- A real Postgres database that keeps your users' accounts, balances,
  and trades permanently (not the 30-day-then-deleted kind)
- Zero monthly cost

**The one tradeoff you already said is fine:** the free backend "spins
down" after 15 minutes with no visitors, and takes about a minute to
wake back up on the next visit. Nothing is lost when this happens (your
data lives in the database, not on the server itself) — it's just a
short pause the first visitor of the day sees.

---

## Before you start

You'll need free accounts on three services. Create them now if you
don't already have them:

1. **GitHub** (github.com) — where your code lives so Render can deploy it.
2. **Supabase** (supabase.com) — your real database.
3. **Render** (render.com) — hosts both your backend and your frontend.

---

## Step 1 — Create your database (Supabase)

1. Go to supabase.com, sign up, and click **New Project**.
2. Give it any name (e.g. "forecast"), set a database password (save it
   somewhere — you'll need it in a moment), pick the region closest to
   you, and click **Create new project**. This takes about two minutes.
3. Once it's ready, go to **Project Settings → Database**.
4. Under **Connection string**, switch to the **Session pooler** tab
   (not "Direct connection" — the direct one is IPv6-only on the free
   tier and will silently fail to connect from Render). Copy that
   connection string. It looks like:
   ```
   postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-xxxxx.pooler.supabase.com:5432/postgres
   ```
5. Replace `[YOUR-PASSWORD]` with the database password from step 2, and
   change `postgresql://` to `postgresql+psycopg2://` at the very start
   (the backend's driver needs that exact prefix). Save this final
   string somewhere — this is your `DATABASE_URL`.

That's your permanent database. It's free forever, doesn't expire after
30 days the way Render's own free Postgres does, and the only catch is
it "pauses" itself after a week of zero activity — the next request to
your site automatically wakes it back up.

---

## Step 2 — Push your code to GitHub

If this project isn't already pushed to a GitHub repo, do that now:

```bash
cd path/to/Forecast
git add -A
git commit -m "Ready for deployment"
```

Then, on github.com, click **New repository**, name it (e.g.
`forecast`), leave it empty (no README/license), and follow the "push an
existing repository" instructions it shows you — it's a couple of
`git remote add` / `git push` commands using the exact repo URL GitHub
just gave you.

---

## Step 3 — Deploy both services on Render

This repo already includes `render.yaml` at its root — a blueprint that
tells Render exactly what to create. This is the fastest path:

1. Go to dashboard.render.com, sign up (you can sign up with your GitHub
   account, which also connects them), and click **New +** → **Blueprint**.
2. Pick the `forecast` repo you just pushed. Render will read
   `render.yaml` and show you a preview: one web service
   (`forecast-backend`) and one static site (`forecast-frontend`).
3. Click **Apply**. Render will ask you to fill in a few values it
   couldn't guess on its own — this is normal, it's exactly the
   `sync: false` entries in `render.yaml`:
   - `DATABASE_URL` → paste the connection string from Step 1.
   - `FRONTEND_BASE_URL`, `CORS_ORIGINS`, `VITE_API_BASE_URL` → see Step 4,
     you can leave these blank for now and fill them in right after.
4. Click through and let it deploy. The backend build runs
   `pip install`, then `alembic upgrade head` (creates every database
   table), then starts the API server. The frontend build runs
   `npm install && npm run build`. Both take a few minutes the first time.

---

## Step 4 — Fill in the two URLs (the chicken-and-egg step)

Your backend and frontend each need to know the other's URL, but neither
URL exists until Render assigns one. So:

1. Once both services show as **Live** in the Render dashboard, copy
   each one's URL from the top of its page (something like
   `https://forecast-backend-xxxx.onrender.com` and
   `https://forecast-frontend-xxxx.onrender.com`).
2. Open the **forecast-backend** service → **Environment** tab, and set:
   - `FRONTEND_BASE_URL` = your frontend's URL, no trailing slash
   - `CORS_ORIGINS` = your frontend's URL, no trailing slash
3. Open the **forecast-frontend** service → **Environment** tab, and set:
   - `VITE_API_BASE_URL` = your backend's URL + `/api/v1`
     (e.g. `https://forecast-backend-xxxx.onrender.com/api/v1`)
4. Saving an environment variable triggers a redeploy of that service
   automatically — wait for both to finish (~2–5 minutes).

Visit your frontend URL. You should see the login/create-account screen.

---

## Step 5 — Create your first account, then make it admin

There's deliberately no API endpoint that grants admin rights (an
endpoint like that would itself need to be protected by... an admin).
Instead:

1. On your live site, click **Create Account** and register normally —
   this is a real account in your real database now.
2. On your own computer, open a terminal in `forecast-backend/` and set
   `DATABASE_URL` to the *exact same* Supabase connection string from
   Step 1 (easiest way: copy your local `.env` to a temporary file and
   change just that one line, or `export DATABASE_URL="postgresql+psycopg2://..."`
   before running the next command).
3. Run:
   ```bash
   python3 scripts/make_admin.py you@example.com
   ```
4. Log out and back in on the live site (your old login token doesn't
   know about the new role until you get a fresh one). You're now an
   admin — this unlocks the admin endpoints in Step 6 below.

---

## Step 6 — Tournaments are tracked automatically (usually nothing to do here)

As of this version, you don't need to manually pick and track
tournaments any more. Every ~45 seconds (see
`OSIRION_SYNC_INTERVAL_SECONDS` in `render.yaml`), the backend:

1. Checks every tournament window Osirion currently has open.
2. Classifies each one against a set of admin-editable rules (see
   `app/services/tournament_classification_service.py`) — by default:
   **Cash Cup tier** = Reload Cash Cup Finals + FNCS Division practice
   finals (any region); **Global tier** = EWC (Esports World Cup) + FNCS
   Global Championship; **Basic FNCS tier** = plain FNCS Finals, tracked
   once per season and skipped entirely during a season that already has
   a Globals event. Anything that looks like a Victory Cup, a skin-themed
   promotional cup, or doesn't match a rule at all is left alone — never
   auto-tracked.
3. Starts tracking every match automatically (creating the internal
   Tournament for you), then syncs standings and pays out dividends the
   same way it always did once each window's end time passes.

You'll see new tournaments simply appear on the Dashboard and the
Tournaments page's **📅 Calendar** tab (ordered soonest-first, each with
its total dividend pool) with no admin action needed. A
"last synced Xs ago" indicator shows the auto-sync is alive.

**If you ever want to adjust the rules or payouts (all via `/docs` —
Swagger UI, same login/Authorize steps as before: log in via
**POST /api/v1/auth/login**, copy `access_token`, paste the raw token
(no "Bearer" prefix) into **Authorize**):**

- **GET/POST `/api/v1/admin/osirion/classification-rules`** — see or
  change which name patterns map to which tier, or add an exclusion (a
  rule with no `tournament_type` means "never track a match").
- **GET/POST `/api/v1/admin/economic-parameters`** — the dollar amount
  each tier's dividend pool pays (`dividend.cash_cup_pool`,
  `dividend.fncs_pool`, `dividend.global_pool` — already set so Cash Cup
  pays least, FNCS pays more, and Global/EWC pays the most).
- **GET/POST `/api/v1/admin/region-multipliers`** — a per-region scale
  factor on top of a tier's pool (e.g. an EU or NAC Cash Cup pays the
  full pool; a smaller region's Cash Cup pays a scaled-down amount of the
  same pool). EU and NAC default to full payout; other regions default
  lower, roughly by relative competitive scene size.
- **POST `/api/v1/admin/osirion/auto-track-now`** — run the
  classify-and-track pass immediately instead of waiting for the next
  45-second cycle (handy right after changing a rule).

Set `OSIRION_AUTO_TRACK_ENABLED=false` in Render's environment variables
to go back to the old fully-manual flow, which still exists if you ever
need it:

1. **GET /api/v1/admin/osirion/available-tournaments** — every trackable
   window, each with `leaderboard_event_id`, `leaderboard_event_window_id`,
   `begin_time`, `end_time`, and a `display_name`.
2. Copy one whole window object into
   **POST /api/v1/admin/osirion/track-tournament**, adding `name` and
   `tournament_type` yourself (`region` is optional).
3. **GET /api/v1/admin/osirion/tracked-tournaments** and
   **POST /api/v1/admin/osirion/tournaments/{tournament_id}/sync-now** to
   check on or force-refresh a specific one.

You can also still enter tournaments fully manually
(`POST /api/v1/admin/tournaments` + `.../results` + `.../finalize`) for
anything Osirion doesn't have — every approach coexists fine.

---

## Step 7 — Verify everything end to end

- [ ] Visit your frontend URL, create a second (non-admin) test account,
      confirm it starts with the real $1,000,000 balance
- [ ] Buy and sell a player's shares, confirm the trade goes through and
      the price updates
- [ ] Confirm the live tournament leaderboard shows up on the Dashboard
      once you've tracked one (Step 6)
- [ ] Try **Forgot password** on the login screen — it should say
      "if that email is registered..." either way (this is intentional,
      see the note below), and you should see the actual reset link
      appear in your backend's logs (Render dashboard → your backend
      service → **Logs**, search for "Password reset requested")

---

## What's NOT fully wired yet, on purpose

**Password reset emails aren't actually sent yet.** Right now,
`EMAIL_PROVIDER=console` means the reset link only gets written to your
server logs, not emailed to the user. Until you turn on real email
(next section), the only way for someone to actually recover their
password is you reading the link out of the logs and sending it to them
yourself. This was a deliberate "don't worry about it for now" choice —
here's how to close that gap whenever you're ready:

### Turning on real password-reset emails (Resend, ~10 minutes)

1. Go to resend.com, sign up (free tier: 3,000 emails/month).
2. Create an API key (**API Keys** in their dashboard).
3. In Render, open **forecast-backend → Environment**, and add:
   - `EMAIL_PROVIDER` = `resend`
   - `RESEND_API_KEY` = the key you just created
4. Save — this redeploys the backend automatically. That's the entire
   change; the code already knows how to use it
   (`app/services/email_service.py`).
5. Optional: by default, emails come from `onboarding@resend.dev`, which
   works immediately but looks generic. If you own a domain, Resend can
   walk you through verifying it so emails come from
   `noreply@yourdomain.com` instead — not required to make this work,
   just more polished.

(Note: this uses Resend's HTTPS API, not raw SMTP, deliberately —
Render's free web services block the standard SMTP ports, so an
SMTP-based email provider would silently fail there.)

---

## Everything that runs automatically once deployed

- **Bot trading** — background liquidity, ticking every 20 seconds
- **Osirion tournament auto-tracking** — classifies and starts tracking
  new Cash Cup / FNCS / Global tournaments every 45 seconds, per
  admin-editable rules (see Step 6) — set `OSIRION_AUTO_TRACK_ENABLED=false`
  to disable and go back to fully manual
- **Osirion tournament sync** — checks every tracked tournament every 45
  seconds, finalizes + pays dividends automatically once a window ends
- **Live price feed** — pushed to connected browsers over WebSocket
- **Database migrations** — run automatically on every deploy, as part
  of the build step (`alembic upgrade head` chained onto `buildCommand`
  in `render.yaml` — Render's free tier doesn't support the separate
  `preDeployCommand` field, so this runs it during build instead, which
  has the same effect: once per deploy, always before the new code starts)

## Everything that still needs a manual admin action

- Adding new players (`POST /api/v1/players` — admin-only, but not under
  the `/admin` path prefix in `/docs`, it's grouped under the "players"
  tag — or ask me to build a proper admin UI for this later if typing
  JSON into `/docs` gets old)
- Tracking a tournament that doesn't match any classification rule (e.g.
  a genuinely new tournament format Osirion adds later) — add a new rule
  via `POST /api/v1/admin/osirion/classification-rules`, or track it
  manually the old way (Step 6's fallback flow)
- Manually entering results for a tournament Osirion doesn't cover
- Adjusting economic parameters (fees, dividend curve, starting balance,
  per-tier dividend pools) via `GET/POST /api/v1/admin/economic-parameters`,
  and per-region payout scale factors via
  `GET/POST /api/v1/admin/region-multipliers`
- Cleaning up any leftover test data if `scripts/smoke_test.py` is ever
  run against the real DATABASE_URL by mistake (it's meant for a
  scratch/dev database) -- `python3 scripts/cleanup_smoke_test_data.py`
  finds it (dry run by default; add `--confirm` to actually delete)

---

## If you outgrow the free tier later

Two specific limits to know about, so nothing surprises you:

- **750 free instance-hours/month** on Render, shared across your
  services — but a spun-down service doesn't count against this, so a
  low-traffic site essentially never hits it.
- **No horizontal scaling** on the free plan (only ever one backend
  instance) — this is exactly why the whole setup runs with
  `REDIS_ENABLED=false` (see `app/core/config.py`): a single instance
  doesn't need Redis to coordinate with other instances that don't
  exist. If you ever upgrade to a paid Render plan and add a second
  instance, set `REDIS_ENABLED=true`, point `REDIS_URL` at a real Redis
  (Upstash's free tier works, or Render's own paid Key Value), and run
  a separate `rq worker forecast-default --url $REDIS_URL` process
  alongside your web service.

Everything else (custom domain, more compute, backups) is a plan
upgrade in the Render dashboard whenever you actually need it — nothing
in the code needs to change to support that later.
