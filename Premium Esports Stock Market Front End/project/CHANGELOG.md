# What changed and why

## Removed (dead weight from the Figma AI export)
- `components/PlayerProfile.tsx` — a full page player-profile component that was never wired into the app (App.tsx only ever opened `PlayerModal`). Duplicate, unused code.
- `components/ui/*` — the entire shadcn/ui kit (48 files). Nothing in the app imports it; every screen is hand-built with Tailwind. Pure dead weight.
- `components/figma/ImageWithFallback.tsx` — unused, no image assets exist anywhere in the app.
- `default_shadcn_theme.css` — unused leftover theme file.
- `package.json` trimmed from 50+ dependencies down to the 4 actually imported anywhere (`lucide-react`, `motion`, `recharts`) plus the Vite/Tailwind build tooling. Everything else (MUI, Radix, react-router, react-hook-form, react-dnd, embla-carousel, react-slick, date-fns, cmdk, vaul, sonner, canvas-confetti, etc.) was dead weight pulled in by the shadcn kit that's now gone.

## Fixed bugs / inconsistencies
- **Portfolio numbers didn't match each other.** The Dashboard hero banner hard-coded "+$1,247.80 today" and "+37.4% all time" — numbers that were never actually computed from the mock holdings. The Portfolio page computed its own (correct) numbers from the same data and got different results (~$304 today, ~16% all-time). Both pages now read from one derived `PORTFOLIO_SUMMARY` in `mockData.ts`, computed from actual share counts × prices, so they can never drift apart again.
- **User identity was inconsistent.** Sidebar said "Kyle Miller", the Dashboard greeting said "Kyle's Portfolio", and the leaderboard listed the same person as "You" — and clicking your own leaderboard row opened a profile card that redundantly read "You [YOU]". Added a single `CURRENT_USER` object everything now references.
- **Stale hard-coded date.** The Dashboard always said "Thursday, July 24" regardless of the actual date. Now computed from the real current date.
- **Broken filter dead-end.** The Market region filter included OCE and BR chips even though zero players in the roster belong to those regions — clicking them silently showed "No players match """ (literal empty quotes). Filter chips are now derived from the actual roster (`ACTIVE_REGIONS`), and the empty-state message is fixed for the no-search case.
- **Data bug:** the "DreamHack Fall 2026" tournament had its display name hard-coded as "DreamHack Fall 2025" (didn't match its own id/date).
- **Duplicated component:** `SparkLine` was copy-pasted verbatim into both `Dashboard.tsx` and `Markets.tsx`. Extracted into `components/SparkLine.tsx`.
- **Hard-coded badge:** the sidebar's "Events" nav badge was a hard-coded "3" instead of the real upcoming-tournament count.

## Authenticity fix (this audience will notice)
The tournament data used branding like "FNCS Chapter 3 Season 3/4 Grand Finals" — Fortnite's real competitive scene moved past Chapter 3 (2022–23) years ago, and current FNCS events are called "Majors" plus a season-ending "Global Championship" (verified against current sources). To an audience that watches competitive Fortnite closely, stale chapter numbers would read as an obvious tell that the app wasn't made by people who follow the scene. Renamed events to the current, evergreen naming scheme so it won't look dated and won't need yearly upkeep.

## Trust / clarity additions
- Added a small, permanent disclaimer in the sidebar and the trade panel: this is a play-money game with simulated stats, not real trading or real news about the named players. The news feed and player bios read like real journalism about real people; a one-line disclosure keeps that honest without breaking the fun tone.
- `ATTRIBUTIONS.md` updated to reflect only the libraries actually used, plus the same simulated-data disclosure.

## New: mobile layout
The app had zero responsive handling at the shell level — a fixed 200px sidebar with no fallback, which breaks completely on a phone screen (the primary device for this audience). Added a bottom tab bar (`MobileNav` in `Sidebar.tsx`) that takes over below the `md` breakpoint, matching the pattern this audience already knows from mobile trading/fantasy-sports apps. The desktop rail is unchanged above that breakpoint.

## New: added depth without losing beginners
- `Player` already carried unused fields (52-week high/low, market cap, volume vs. average volume, ELO). Surfaced them in the trade modal behind a collapsed "Show advanced stats" toggle, each with a one-line plain-English explainer — so a first-time user isn't confronted with stock jargon, but a more experienced user gets real depth.
- Added a 30D/90D range toggle to the player price chart (previously locked to 30 days).
- `PORTFOLIO_PERFORMANCE_30D` (a 30-day portfolio-value + market-average dataset) existed in `mockData.ts` but was never rendered anywhere. Added a "Performance, Last 30 Days" chart to the Portfolio page comparing your squad's value against the average investor — a genuinely useful, standard "am I beating the market" view that reuses data that was already built.

## Left as-is, flagged for you
- Kept the real pro player names (Bugha, Clix, MrSavage, etc.) rather than fictionalizing them — this mirrors the standard fantasy-sports model (same legal basis DraftKings/FanDuel rely on: public performance stats aren't proprietary), and it's core to the "prove your Fortnite knowledge" hook. Worth knowing this is a product/legal call, not just a design one, if you want a second opinion before shipping.
- I did **not** invent additional real-sounding pro names for regions with no roster coverage (e.g., OCE, BR) — that would mean fabricating specific identities/stats we can't verify, which is exactly the kind of thing you flagged as "shouldn't be in it." Instead the region filter now only ever shows regions with real roster data behind them.
