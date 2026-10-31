#!/usr/bin/env python3
"""
Writes a believable 2026 price history for every active player, so charts do not start the day the bots did.

No trades are made. Each player's price path is a model, built from the same pieces the live bots use:

  * Fair value AS OF each date: the bots' fair price (yearly dividends per share / 10% target yield,
    bot_trading_service._fair_from_income) recomputed from only the results that had finished by then, so a player's
    line steps up or down as results come in. Before a player has results it starts from a reputation prior.
  * Daily noise (about 1%) that pulls back toward fair value, plus a quicker catch-up in the few days after a result.
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

DAILY_SIGMA = 0.010          # day-to-day noise on the log price
KAPPA_BASE = 0.08            # daily pull back to the target
KAPPA_REACT = 0.45           # faster pull in the days right after a result lands
REACT_DAYS = 3.0
RUNUP = 0.02                 # log-price bump building up to a tournament start (players in the field)
RUNUP_DAYS = 3.0
EXDIV = 0.015                # log-price dip after the start (dividend already locked in)
EXDIV_DAYS = 2.0
MIN_PRICE = 0.01


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2026-01-01", help="First day of history (default 2026-01-01).")
    ap.add_argument("--step-days", type=float, default=1.0, help="Days between baseline points (default 1).")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true", help="Compute and summarise, write nothing.")
    ap.add_argument("--player", default=None, help="Only this gamertag (for a quick look).")
    ap.add_argument("--reset-prices", action="store_true",
                    help="ONE-TIME REPRICE: cancel every open order, delete ALL price history (real trades included) for "
                         "the roster, and rebuild it so every stock ends at its dividend-based fair price. Restart the "
                         "backend right after (it keeps order books in memory).")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc)
    t_start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
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
        new_rows: list[dict] = []
        per_player_pts = []
        big_corr = 0
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
                react = (t - last_cp).total_seconds() / 86400.0 < REACT_DAYS and last_cp > t_start
                return tgt, (KAPPA_REACT if react else KAPPA_BASE)

            # time grid: one point per step-day (jittered inside the day) + every tournament start / finish of this player
            times = []
            d = t_start
            while d < end_ts:
                times.append(d + timedelta(hours=rng.uniform(8, 20)) if args.step_days >= 1 else d)
                d += timedelta(days=args.step_days)
            for (done, start, _v) in my_events:
                for t in (start, done + timedelta(hours=1)):
                    if t_start <= t < end_ts:
                        times.append(t)
            times = sorted({t for t in times if t_start <= t < end_ts})
            if not times:
                continue

            x = target(times[0])[0]
            prev = times[0]
            path = [(times[0], x)]
            for t in times[1:]:
                dt = max((t - prev).total_seconds() / 86400.0, 1e-3)
                tgt, kappa = target(t)
                x += (1.0 - math.exp(-kappa * dt)) * (tgt - x) + DAILY_SIGMA * math.sqrt(dt) * rng.gauss(0, 1)
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
            prices = [(t, max(MIN_PRICE, math.exp(v))) for t, v in path]
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
        if args.dry_run:
            print("Dry run: nothing written.")
            return
        if args.reset_prices and not args.yes:
            print("Refusing to reset prices without --yes. Back up the database first, read the impact list above, then re-run with --yes.")
            return

        if args.reset_prices:
            from app.models.order import Order, OrderStatus
            from app.services import order_service
            from app.services.exceptions import ServiceError
            open_orders = db.query(Order.id, Order.user_id).filter(Order.player_id.in_(pids), Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED])).all()
            cancelled = 0
            for n, (oid, uid) in enumerate(open_orders, 1):
                try:
                    order_service.cancel_order(db, uid, oid)
                    cancelled += 1
                except ServiceError:
                    pass
                if n % 500 == 0:
                    db.commit()
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
        db.commit()
        print("Done. Charts now show 2026 history; reload the site.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
