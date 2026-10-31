#!/usr/bin/env python3
"""
Writes a believable 2026 price history for every active player, so charts do not start the day the bots did.

No trades are made. Each player's price path is a model, built from the same pieces the live bots use:

  * Fair value AS OF each date: the bots' fair price (yearly dividends per share / 10% target yield,
    bot_trading_service._fair_from_income) recomputed from only the results that had finished by then, so a player's
    line steps up or down as results come in. Before a player has results it starts from a reputation prior.
  * Quiet-market noise (about 1.2% a day, fat-tailed, capped by the live market's own hourly move limits) that slowly pulls back to fair value; faster noise around the player's own tournaments; and an immediate jump when a result lands (the live re-rate). Top stocks get hourly points for the last week so 1D/1W charts look like a live market.
  * Dividend timing for players in the field: a small run-up before a tournament starts and a small dip just after
    (the dividend is locked in at the start).
  * Missed events: a player who normally plays their region's qualifying events but is not in one slips a little
    (app/services/missed_event_service.py -- the live bots apply the same rule).
  * The path is bent so it lands exactly on the player's first REAL trade price (or runs to today if the player has
    never traded), so the history joins the live market without a jump.

Synthetic rows are stored with volume = 0 (real trades always have volume > 0), which makes this safe to re-run: every
earlier run's synthetic rows are deleted first. Real trades are never touched.

Usage (from forecast-backend):
    python3 scripts/simulate_price_history.py --dry-run          # print a summary, write nothing
    python3 scripts/simulate_price_history.py                    # write the history
    python3 scripts/simulate_price_history.py --step-days 2      # fewer points = smaller database (default 1 per day)
    python3 scripts/simulate_price_history.py --reset-prices     # one-time reprice after the fair-value formula changed
    python3 scripts/simulate_price_history.py --seed 7 --start 2026-01-01
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine.dividend_calculator import placement_payout_fraction  # noqa: E402
from app.models.player import Player, PriceSnapshot  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.services import bot_trading_service as bots  # noqa: E402
from app.services import economic_params_service, missed_event_service  # noqa: E402

HOURLY_SIGMA = 0.0025        # quiet-market noise on the log price per sqrt(hour) (~1.2% a day): many small bot trades against a
                             # damped reference price, with fat tails (Student-t) because a few trades are bigger than the rest
EVENT_SIGMA_MULT = 4.0       # noise is this much larger from 2h before one of the player's events starts until 6h after it ends
CALM_HOURLY_CAP = 0.02       # the live market's own limits (market.calm_hourly_move / market.event_hourly_move): the reference
EVENT_HOURLY_CAP = 0.12      # price may move at most this much an hour; the history obeys them so it cannot look wilder than live
RESULT_JUMP = 0.9            # when a result lands the live re-rate moves the price at once, to ~this share of the way to the new fair
KAPPA_BASE = 0.08            # daily pull back toward fair value (bots buying under it, selling over it)
RUNUP = 0.02                 # log-price bump building up to a tournament start (players in the field)
RUNUP_DAYS = 3.0
EXDIV = 0.015                # log-price dip after the start (dividend already locked in)
EXDIV_DAYS = 2.0
MIN_PRICE = 0.01
HIRES_PLAYERS = 150          # the most valuable stocks (the ones that really trade) get intraday detail
RAMP_DAYS = 21.0             # with --reset-prices: the last this-many days bend smoothly onto the live fair price


def _smoothstep(x: float) -> float:
    """0 before the ramp starts, 1 once it is over, an S-curve in between (no kink at either end)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=None,
                    help="First day of history, YYYY-MM-DD (default: 180 days ago). Our results only go back to early 2026, so the "
                         "first months of 'dividends so far' understate what players had really earned; a shorter history "
                         "avoids a fake climb from a too-low starting price.")
    ap.add_argument("--step-days", type=float, default=1.0, help="Days between baseline points (default 1).")
    ap.add_argument("--hourly-days", type=float, default=7.0, help="Days of hourly points for the top stocks (4-hourly for the 3 weeks before that, daily before).")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true", help="Compute and summarise, write nothing.")
    ap.add_argument("--player", default=None, help="Only this gamertag (for a quick look).")
    ap.add_argument("--reset-prices", action="store_true",
                    help="ONE-TIME REPRICE: cancel every open order, delete ALL price history (real trades included) for "
                         "the roster, and rebuild it so every stock ends at its dividend-based fair price. Restart the "
                         "backend right after (it keeps order books in memory).")
    ap.add_argument("--cancel-orders", action="store_true",
                    help="With --reset-prices: cancel every open order (slow, one by one) instead of the default, which keeps them and "
                         "rescales each order's limit price by (new price / old price) of its stock.")
    ap.add_argument("--yes", action="store_true", help="Required together with --reset-prices to actually write it.")
    ap.add_argument("--market-multiple", type=float, default=None,
                    help="LAUNCH PRICE LEVEL (with --reset-prices): start the market at this multiple of the cash players hold "
                         "(e.g. 1.5). The target yield is solved from it and stored as the platform parameter market.target_yield; "
                         "each stock's share of the total is its share of expected dividends.")
    ap.add_argument("--market-cash", type=float, default=None,
                    help="The cash to take the multiple of, in dollars (e.g. 305000000 for 255 bots + 50 players at $1M). "
                         "Default: the cash actually in all non-House wallets right now.")
    args = ap.parse_args()
    if args.market_multiple and not args.reset_prices:
        ap.error("--market-multiple changes every price, so it only works together with --reset-prices")

    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc)
    if args.start:
        t_start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    else:
        t_start = (now - timedelta(days=180)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"History window: {t_start.date()} -> {now.date()}")
    db = SessionLocal()
    try:
        players = db.query(Player.id, Player.gamertag, Player.region, Player.ipo_price, Player.total_shares_outstanding).filter(Player.is_active.is_(True)).all()
        if args.player:
            players = [p for p in players if p.gamertag.lower() == args.player.lower()]
        if not players:
            print("No matching active players.")
            return
        pids = [p.id for p in players]
        shares_of = {p.id: max(1, p.total_shares_outstanding) for p in players}
        print(f"{len(players)} players")

        # ---- results -------------------------------------------------------------------------------------------
        rows = (
            db.query(PlacementResult.player_id, PlacementResult.tournament_id, PlacementResult.placement,
                     Tournament.start_time, Tournament.end_time)
            .join(Tournament, Tournament.id == PlacementResult.tournament_id)
            .filter(PlacementResult.player_id.in_(pids), Tournament.start_time.isnot(None))
            .all()
        )
        tids = {r[1] for r in rows}
        field = {tid: n for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(tids)).group_by(PlacementResult.tournament_id).all()}
        pools = bots._tournament_pool_amounts(db, list(tids))
        curve = economic_params_service.get_placement_curve(db)

        # per player: [(finished_at, started_at, value_of_result)] oldest first
        results: dict[uuid.UUID, list[tuple[datetime, datetime, float]]] = defaultdict(list)
        for pid, tid, placement, start, end in rows:
            start = _aware(start)
            done = _aware(end) if end is not None else start + timedelta(days=1)
            frac = placement_payout_fraction(placement, max(1, field.get(tid, 1)), curve)
            results[pid].append((done, start, float(pools.get(tid, Decimal("0")) * frac)))
        for lst in results.values():
            lst.sort()

        first_seen = min((s for lst in results.values() for (_d, s, _v) in lst), default=None)
        if first_seen is None:
            print("No usable tournament results yet -- nothing to simulate from.")
            return

        # ---- price LEVEL: yield from the chosen market value ------------------------------------------------------
        from app.services import fair_price_service

        if args.market_multiple:
            from app.models.user import User
            from app.models.wallet import Wallet
            from app.services.house_account import HOUSE_ACCOUNT_EMAIL

            if args.market_cash:
                cash = float(args.market_cash)
                cash_note = "given"
            else:
                house_id = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).scalar()
                q = db.query(func.coalesce(func.sum(Wallet.cash_balance), 0))
                if house_id is not None:
                    q = q.filter(Wallet.user_id != house_id)
                cash = float(q.scalar() or 0)
                cash_note = "all non-House wallets right now"
            target_mv = cash * args.market_multiple
            y = fair_price_service.solve_target_yield(db, target_mv)
            # Store it now (flushed, not committed): every later fair-price call in this script reads the parameter.
            economic_params_service.set_param(db, "market.target_yield", Decimal(str(round(y, 6))))
            db.flush()
            fair_price_service.refresh_target_yield(db)
            total_shares_priced = sum(shares_of.values())
            print(f"\nLAUNCH LEVEL: cash {cash:,.0f} ({cash_note}) x {args.market_multiple} = market value {target_mv:,.0f}"
                  f" -> target yield {y * 100:.2f}% (average ~${target_mv / max(1, total_shares_priced):,.2f} a share over {total_shares_priced:,} shares)")
        else:
            fair_price_service.refresh_target_yield(db)
            print(f"\nUsing the stored target yield {bots.TARGET_YIELD * 100:.2f}%.")

        def fair_asof(pid: uuid.UUID, at: datetime) -> float:
            """The live bots' fair price (yearly dividends per share / target yield) using only results finished by `at`."""
            ev = [(d, v) for (d, _s, v) in results.get(pid, ())]
            return float(bots._fair_from_income(bots.income_at(ev, at, first_seen) / shares_of[pid]))

        final_fair_all = {p.id: fair_asof(p.id, now) for p in players}
        sorted_final = sorted(final_fair_all.values())
        median_final = sorted_final[len(sorted_final) // 2]

        # Checkpoints where fair value can change: every result's finish time in range, plus the start.
        checkpoints = sorted({t_start} | {d for lst in results.values() for (d, _s, _v) in lst if t_start < d <= now})

        missed = defaultdict(list)
        for pid, when, pen in missed_event_service.missed_events(db, {p.id: p.region for p in players}, t_start, now):
            missed[pid].append((when, pen))

        # ---- real-trade bridge points ----------------------------------------------------------------------------
        first_real_t = {} if args.reset_prices else {pid: _aware(t) for pid, t in db.query(PriceSnapshot.player_id, func.min(PriceSnapshot.recorded_at)).filter(PriceSnapshot.volume > 0, PriceSnapshot.player_id.in_(pids)).group_by(PriceSnapshot.player_id).all()}
        first_real_p: dict[uuid.UUID, float] = {}
        for pid, t in first_real_t.items():
            px = db.query(PriceSnapshot.price).filter(PriceSnapshot.player_id == pid, PriceSnapshot.volume > 0, PriceSnapshot.recorded_at == t).limit(1).scalar()
            if px is not None:
                first_real_p[pid] = float(px)

        # ---- simulate ----------------------------------------------------------------------------------------------
        from app.engine import market_policy

        fair_live = fair_price_service.compute_fair(db)
        band_low = economic_params_service.get_param(db, "market.band_low")
        band_high = economic_params_service.get_param(db, "market.band_high")
        new_rows: list[dict] = []
        name_has_fair = {p.gamertag: (p.id in fair_live) for p in players}
        per_player_pts = []
        big_corr = 0
        rank_of = {pid: i for i, (pid, _f) in enumerate(sorted(final_fair_all.items(), key=lambda kv: -kv[1]))}
        for p in players:
            end_ts = first_real_t.get(p.id, now)
            if end_ts <= t_start + timedelta(days=2):
                continue  # real trading already covers (almost) all of the window
            # Before a player has results the market still has a reputation to go on, so start from a prior that leans
            # (in log terms) 60% toward where the player ends up and 40% toward the typical player, and let results
            # take over: weight on results = n / (n + 2) after n finished events.
            prior_log = 0.6 * math.log(final_fair_all[p.id]) + 0.4 * math.log(median_final)
            fair_at = []  # [(checkpoint_time, log fair)]
            for c in checkpoints:
                n = sum(1 for (d, _s, _v) in results.get(p.id, ()) if d <= c)
                if n == 0:
                    fair_at.append((c, prior_log))
                    continue
                w = n / (n + 2.0)
                fair_at.append((c, w * math.log(fair_asof(p.id, c)) + (1.0 - w) * prior_log))
            my_events = results.get(p.id, [])

            def target(t: datetime) -> tuple[float, float]:
                """(log target price, kappa) at time t."""
                lf = fair_at[0][1]
                last_cp = fair_at[0][0]
                for c, f in fair_at:
                    if c <= t:
                        lf, last_cp = f, c
                    else:
                        break
                tgt = lf
                for (d, s, _v) in my_events:
                    ds = (s - t).total_seconds() / 86400.0
                    if 0 < ds <= RUNUP_DAYS:
                        tgt += RUNUP * (1.0 - ds / RUNUP_DAYS)
                    elif -EXDIV_DAYS <= ds <= 0:
                        tgt -= EXDIV * (1.0 + ds / EXDIV_DAYS)
                tgt -= missed_event_service.decayed_penalty(missed.get(p.id, []), t)
                return tgt, KAPPA_BASE

            # Time grid. Baseline: one point a day; the most valuable stocks get 4-hourly points for the 3 weeks before the
            # hourly stretch and hourly points for the last --hourly-days (that is how a live chart looks at 1D / 1W zoom).
            # Every one of the player's tournaments adds points around it: before the start, the start, the finish, and the
            # moment the result is re-rated.
            hires = rank_of[p.id] < HIRES_PLAYERS
            times = []
            d = t_start
            hourly_from = end_ts - timedelta(days=args.hourly_days)
            fourh_from = hourly_from - timedelta(days=21)
            while d < end_ts:
                if hires and d >= hourly_from:
                    times.append(d)
                    d += timedelta(hours=1)
                elif hires and d >= fourh_from:
                    times.append(d)
                    d += timedelta(hours=4)
                else:
                    times.append(d + timedelta(hours=rng.uniform(8, 20)) if args.step_days >= 1 else d)
                    d += timedelta(days=args.step_days)
            jump_times = set()
            windows = []  # (from, to) while this player's own events make the market move faster
            for (done, start, _v) in my_events:
                rt = done + timedelta(minutes=30)
                for t in (start - timedelta(hours=2), start, done, rt, done + timedelta(hours=3)):
                    if t_start <= t < end_ts:
                        times.append(t)
                if t_start <= rt < end_ts:
                    jump_times.add(rt)
                windows.append((start - timedelta(hours=2), done + timedelta(hours=6)))
            times = sorted({t for t in times if t_start <= t < end_ts})
            if not times:
                continue

            def in_event(t: datetime) -> bool:
                return any(a <= t <= b for a, b in windows)

            def noise() -> float:
                # Student-t with 4 degrees of freedom, scaled to unit variance: mostly small moves, occasionally a bigger one.
                z = rng.gauss(0, 1)
                chi = sum(rng.gauss(0, 1) ** 2 for _ in range(4))
                return z / math.sqrt(chi / 4.0) / math.sqrt(2.0)

            x = target(times[0])[0]
            prev = times[0]
            path = [(times[0], x)]
            for t in times[1:]:
                dt = max((t - prev).total_seconds() / 86400.0, 1e-4)
                hours = dt * 24.0
                tgt, kappa = target(t)
                evt = in_event(t)
                step = (1.0 - math.exp(-kappa * dt)) * (tgt - x) + HOURLY_SIGMA * (EVENT_SIGMA_MULT if evt else 1.0) * math.sqrt(hours) * noise()
                cap = (EVENT_HOURLY_CAP if evt else CALM_HOURLY_CAP) * max(1.0, hours)
                step = max(-cap, min(cap, step))
                if t in jump_times:
                    # the live re-rate: the price moves at once to (most of) the new fair value, not over several days
                    step += RESULT_JUMP * (tgt - target(t - timedelta(minutes=1))[0])
                x += step
                path.append((t, x))
                prev = t
            # land on the first real trade price
            if p.id in first_real_p and first_real_p[p.id] > 0:
                tgt, kappa = target(end_ts)
                dt = max((end_ts - prev).total_seconds() / 86400.0, 1e-3)
                x_end = x + (1.0 - math.exp(-kappa * dt)) * (tgt - x)
                delta = math.log(first_real_p[p.id]) - x_end
                if abs(delta) > 0.7:
                    big_corr += 1
                span = max((end_ts - path[0][0]).total_seconds(), 1.0)
                path = [(t, v + delta * (((t - path[0][0]).total_seconds() / span) ** 2)) for t, v in path]
            if args.reset_prices and p.id not in first_real_p and p.id in fair_live:
                # BLEND INTO THE LIVE MARKET: the market opens at the live fair price (that is what the bots, the House and the
                # band all work from, and what the market-value target was solved for), so bend the last RAMP_DAYS of the
                # history smoothly onto it. Earlier history is untouched; the chart ends exactly where trading starts.
                delta_end = math.log(float(fair_live[p.id])) - path[-1][1]
                ramp_start = path[-1][0] - timedelta(days=RAMP_DAYS)
                path = [(t, v + delta_end * _smoothstep(((t - ramp_start).total_seconds() / 86400.0) / RAMP_DAYS)) for t, v in path]
            prices = [(t, max(MIN_PRICE, math.exp(v))) for t, v in path]
            if p.id not in first_real_p and p.id in fair_live:
                # The live market clamps every reference price into [band_low, band_high] x its (fluke-shrunk) fair price;
                # end the path inside that band so the chart's last point IS the reference price the market starts from.
                lo_px, hi_px = (float(x) for x in market_policy.band_limits(fair_live[p.id], band_low, band_high))
                prices[-1] = (prices[-1][0], min(max(prices[-1][1], lo_px), hi_px))
            if args.reset_prices and p.id not in first_real_p:
                # A closing point at "now" with the opening price, so there is no gap or jump between the last simulated
                # day and the first live trade (the reference price below is set to exactly this value).
                prices.append((now - timedelta(seconds=30), prices[-1][1]))
            per_player_pts.append((p.gamertag, prices))
            for t, px in prices:
                new_rows.append({"id": uuid.uuid4(), "player_id": p.id, "price": Decimal(str(round(px, 4))), "volume": 0, "recorded_at": t})

        print(f"Built {len(new_rows):,} synthetic points for {len(per_player_pts)} players "
              f"({sum(len(v) for v in missed.values())} missed-event penalties applied; {big_corr} paths needed a big bridge to their first real trade).")
        if not any(missed.values()):
            from collections import Counter
            filled = missed_event_service.fill_regions(db, {p.id: p.region for p in players})
            print("  (no missed events found) player regions:", dict(Counter(missed_event_service.region_key(r) for r in filled.values()).most_common(8)))
            print("  tournaments of the qualifying types, by (type, region):",
                  dict(Counter((t.value, missed_event_service.region_key(r)) for t, r in db.query(Tournament.tournament_type, Tournament.region).filter(Tournament.tournament_type.in_(list(missed_event_service.MISSED_PENALTY)), Tournament.start_time >= t_start).all()).most_common(10)))
        ends = sorted(prices[-1][1] for _, prices in per_player_pts)
        if ends and args.reset_prices:
            sh_by_name = {p.gamertag: shares_of[p.id] for p in players}
            mv_end = sum(prices[-1][1] * sh_by_name[tag] for tag, prices in per_player_pts)
            with_fair = [(tag, prices[-1][1] * sh_by_name[tag]) for tag, prices in per_player_pts if name_has_fair.get(tag)]
            without = [(tag, prices[-1][1] * sh_by_name[tag]) for tag, prices in per_player_pts if not name_has_fair.get(tag)]
            print(f"  resulting market value (every share x its new price): {mv_end:,.0f}")
            print(f"    stocks with a results history ({len(with_fair)}): {sum(v for _t, v in with_fair):,.0f}  <- this is what the target is solved for")
            print(f"    stocks with no results at all ({len(without)}): {sum(v for _t, v in without):,.0f}  (priced near the floor; no fair price, so no band)")
        if ends:
            print("  end prices: p10 ${:.2f}  p25 ${:.2f}  median ${:.2f}  p75 ${:.2f}  p90 ${:.2f}  max ${:.2f}".format(
                ends[int(.1 * len(ends))], ends[int(.25 * len(ends))], ends[len(ends) // 2], ends[int(.75 * len(ends))], ends[int(.9 * len(ends))], ends[-1]))
        for tag, prices in sorted(per_player_pts, key=lambda r: -r[1][-1][1])[:6]:
            lo, hi = min(px for _, px in prices), max(px for _, px in prices)
            print(f"  {tag:<22} start ${prices[0][1]:>8.2f}  end ${prices[-1][1]:>8.2f}  range ${lo:.2f}-${hi:.2f}")
        if args.reset_prices:
            # Show what the reprice does to real people's portfolios BEFORE anyone commits to it.
            from app.models.bot import BotProfile
            from app.models.player import Position
            from app.models.user import User
            from app.services import portfolio_service
            from app.services.house_account import HOUSE_ACCOUNT_EMAIL
            skip = {uid for (uid,) in db.query(BotProfile.user_id).all()} | {uid for (uid,) in db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).all()}
            old_px = {pid: float(v) for pid, v in portfolio_service.last_prices(db).items()}
            new_px: dict = {}
            name_to_id = {p.gamertag: p.id for p in players}
            for tag, prices in per_player_pts:
                new_px[name_to_id[tag]] = prices[-1][1]
            per_user: dict = defaultdict(lambda: [0.0, 0.0])
            for uid, pid, qty in db.query(Position.user_id, Position.player_id, Position.quantity).filter(Position.quantity > 0).all():
                if uid in skip or pid not in new_px:
                    continue
                per_user[uid][0] += qty * old_px.get(pid, 0.0)
                per_user[uid][1] += qty * new_px[pid]
            names = {uid: n for uid, n in db.query(User.id, User.display_name).filter(User.id.in_(list(per_user))).all()} if per_user else {}
            print(f"\nImpact on {len(per_user)} real users who hold shares (shares value before -> after the reprice; cash is unchanged):")
            for uid, (before, after) in sorted(per_user.items(), key=lambda kv: -kv[1][0]):
                print(f"  {str(names.get(uid, uid))[:24]:<24} ${before:>12,.0f} -> ${after:>12,.0f}   ({(after / before - 1) * 100 if before else 0:+.0f}%)")

        def reprice_open_orders(apply: bool) -> None:
            """Keep every open limit order, moved by the same percentage as its stock's price: new limit = old limit x
            (new reference / old reference), kept inside the stock's fair-value band. A buy order's cash hold is resized to
            match; if the wallet cannot cover the bigger hold the order is cancelled instead. Sell orders keep their shares."""
            from app.models.order import Order, OrderKind, OrderSide, OrderStatus
            from app.models.wallet import Wallet

            new_ref = {name_to_id_all[tag]: Decimal(str(round(prices[-1][1], 4))) for tag, prices in per_player_pts}
            old_ref = {pid: (ref if ref is not None else None) for pid, ref in db.query(Player.id, Player.reference_price).filter(Player.id.in_(pids)).all()}
            last_old = {pid: Decimal(str(v)) for pid, v in portfolio_service_last_prices().items()}
            fee = economic_params_service.get_param(db, "fees.transaction_fee_pct")
            orders = (
                db.query(Order)
                .filter(Order.player_id.in_(pids), Order.order_kind == OrderKind.LIMIT,
                        Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]))
                .order_by(Order.player_id)
                .all()
            )
            wallets = {w.user_id: w for w in db.query(Wallet).filter(Wallet.user_id.in_({o.user_id for o in orders})).all()} if orders else {}
            kept = cancelled_n = skipped = 0
            ratios = []
            for n, o in enumerate(orders, 1):
                base = old_ref.get(o.player_id) or last_old.get(o.player_id)
                tgt = new_ref.get(o.player_id)
                if not base or not tgt or base <= 0 or o.limit_price is None:
                    skipped += 1
                    continue
                ratio = tgt / Decimal(base)
                ratios.append(float(ratio))
                new_price = (Decimal(o.limit_price) * ratio)
                fair = fair_live.get(o.player_id)
                if fair is not None:
                    lo_px, hi_px = market_policy.band_limits(fair, band_low, band_high)
                    new_price = min(max(new_price, lo_px), hi_px)
                new_price = max(new_price, Decimal("0.01")).quantize(Decimal("0.01"))
                remaining = o.quantity - o.filled_quantity
                if o.side == OrderSide.BUY and remaining > 0:
                    delta = (new_price - Decimal(o.limit_price)) * remaining * (Decimal("1") + fee)
                    w = wallets.get(o.user_id)
                    if w is None or (delta > 0 and w.cash_balance - w.held_balance < delta):
                        if apply and w is not None:
                            w.held_balance = max(Decimal("0"), w.held_balance - Decimal(o.limit_price) * remaining * (Decimal("1") + fee))
                        if apply:
                            o.status = OrderStatus.CANCELLED
                            o.cancelled_at = now
                        cancelled_n += 1
                        continue
                    if apply:
                        w.held_balance = max(Decimal("0"), w.held_balance + delta)
                if apply:
                    o.limit_price = new_price
                kept += 1
                if apply and n % 500 == 0:
                    db.commit()
                    print(f"  {n:,}/{len(orders):,} orders repriced", flush=True)
            med = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
            verb = "Repriced" if apply else "Would reprice"
            print(f"\n{verb} {kept:,} open orders (median change x{med:.2f}; each moved by its stock's price change); "
                  f"{cancelled_n:,} cancelled because the wallet could not cover the larger buy hold; {skipped:,} left unchanged (no price to compare).")
            if apply:
                db.commit()

        name_to_id_all = {p.gamertag: p.id for p in players}

        def portfolio_service_last_prices():
            from app.services import portfolio_service as _ps
            return _ps.last_prices(db)

        if args.reset_prices:
            reprice_open_orders(apply=False) if args.dry_run else None
        if args.dry_run:
            print("Dry run: nothing written.")
            return
        if args.reset_prices and not args.yes:
            print("Refusing to reset prices without --yes. Back up the database first, read the impact list above, then re-run with --yes.")
            return
        # Writing prices/orders: the web server keeps order books and reference prices in memory, so it must not be running.
        from app.services import lease_service
        lease_service.script_guard_or_exit(db, "simulate_price_history")

        if args.reset_prices:
            if not args.cancel_orders:
                reprice_open_orders(apply=True)
            else:
                from app.models.order import Order, OrderStatus
                from app.services import order_service
                from app.services.exceptions import ServiceError
                open_orders = (
                    db.query(Order.id, Order.user_id)
                    .filter(Order.player_id.in_(pids), Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]))
                    .order_by(Order.player_id)  # one stock's order book is loaded once and reused for all its orders
                    .all()
                )
                print(f"Cancelling {len(open_orders):,} open orders one by one (releases each hold; this is the slow part -- progress below). "
                      "Safe to stop and re-run: finished batches are already saved.")
                import time as _time
                t0 = _time.time()
                cancelled = 0
                for n, (oid, uid) in enumerate(open_orders, 1):
                    try:
                        order_service.cancel_order(db, uid, oid)
                        cancelled += 1
                    except ServiceError:
                        pass
                    if n % 100 == 0:
                        db.commit()
                        rate = n / max(_time.time() - t0, 1e-6)
                        print(f"  {n:,}/{len(open_orders):,} cancelled  (~{(len(open_orders) - n) / max(rate, 1e-6) / 60:.1f} min left)", flush=True)
                db.commit()
                print(f"Cancelled {cancelled:,} open orders (holds released).")

            deleted = db.query(PriceSnapshot).filter(PriceSnapshot.player_id.in_(pids)).delete(synchronize_session=False)
            print(f"Removed ALL {deleted:,} old price points.")
        else:
            deleted = db.query(PriceSnapshot).filter(PriceSnapshot.volume == 0, PriceSnapshot.player_id.in_(pids)).delete(synchronize_session=False)
            print(f"Removed {deleted:,} older synthetic points.")
        for i in range(0, len(new_rows), 5000):
            db.bulk_insert_mappings(PriceSnapshot, new_rows[i:i + 5000])
            db.commit()
            print(f"  inserted {min(i + 5000, len(new_rows)):,}/{len(new_rows):,}")
        if args.reset_prices:
            # The market's reference price starts at each stock's last simulated price (already inside its fair band).
            name_to_id = {p.gamertag: p.id for p in players}
            for tag, prices in per_player_pts:
                db.query(Player).filter(Player.id == name_to_id[tag]).update(
                    {Player.reference_price: Decimal(str(round(prices[-1][1], 4)))}, synchronize_session=False
                )
            db.commit()
            print(f"Set the reference price of {len(per_player_pts)} stocks.")
        db.commit()
        print("Done. Charts now show 2026 history; reload the site.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
