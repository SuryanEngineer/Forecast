#!/usr/bin/env python3
"""
Raise (or lower) every dividend pool WITHOUT moving prices.

  1. Pins the market's total fair value (platform parameter market.anchor_value) at what the market is worth today, unless an
     anchor is already set. From then on a stock's fair price is its SHARE of all expected dividends, so the size of the pools
     never changes the price level -- it only changes what holding a stock pays.
  2. Multiplies the five fixed pools (Cash Cup, qualifier, FNCS, Global, Performance Evaluation) by --multiplier.

Dry run by default (prints, changes nothing):
    cd forecast-backend
    python scripts/scale_dividends.py --multiplier 3

Apply it (takes effect within ~10 minutes, when the fair prices are next recomputed):
    python scripts/scale_dividends.py --multiplier 3 --confirm

Other options:
    --anchor 5000000     pin the market value at this many dollars instead of today's
    --anchor-only        only set the anchor (no pool change)
Tournaments with an admin-entered prize pool, and dividends already paid, are not touched.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.player import Player  # noqa: E402
from app.services import economic_params_service as eps, fair_price_service  # noqa: E402

POOL_KEYS = (
    "dividend.cash_cup_pool",
    "dividend.qualifier_pool",
    "dividend.fncs_pool",
    "dividend.global_pool",
    "dividend.performance_eval_pool",
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--multiplier", type=float, default=None, help="Multiply every fixed dividend pool by this (e.g. 3).")
    ap.add_argument("--anchor", type=float, default=None, help="Pin the total market value at this many dollars (default: today's, if no anchor is set).")
    ap.add_argument("--anchor-only", action="store_true", help="Only set the anchor.")
    ap.add_argument("--confirm", action="store_true", help="Write the changes (otherwise a dry run).")
    args = ap.parse_args()
    if args.multiplier is None and not args.anchor_only and args.anchor is None:
        ap.error("give --multiplier, --anchor or --anchor-only")
    if args.multiplier is not None and args.multiplier <= 0:
        ap.error("--multiplier must be positive")

    db = SessionLocal()
    try:
        current_anchor = fair_price_service.anchor_value(db)
        bench = fair_price_service.benchmark(db)
        # The anchor is a total of FAIR prices, so pin it at today's fair total: every fair price then stays exactly where it is.
        # (benchmark's market_value uses reference prices, which can differ a lot from fair prices; it is shown for comparison only.)
        fair = fair_price_service.fair_prices(db, force=True)
        shares = {pid: n for pid, n in db.query(Player.id, Player.total_shares_outstanding).filter(Player.is_active.is_(True)).all()}
        today_mv = sum(float(f) * max(1, shares.get(pid, 1)) for pid, f in fair.items())
        dividends = float(bench["projected_dividends_per_year"])
        print(f"fair value of the whole market today ({len(fair)} stocks): ${today_mv:,.0f}   (reference-price market value: ${float(bench['market_value']):,.0f})")
        print(f"projected dividends per year at today's pools: ${dividends:,.0f} = {dividends / today_mv * 100 if today_mv else 0:.1f}% of fair value\n")

        new_anchor = args.anchor if args.anchor is not None else (current_anchor or today_mv)
        if new_anchor <= 0:
            print("No market value to anchor to (no priced stocks yet); nothing changed.")
            return
        if current_anchor and args.anchor is None:
            print(f"anchor already set: ${current_anchor:,.0f} (kept)")
        else:
            print(f"anchor: ${current_anchor:,.0f} -> ${new_anchor:,.0f}")
            eps.set_param(db, "market.anchor_value", Decimal(str(round(new_anchor, 2))))

        if args.multiplier is not None and not args.anchor_only:
            k = Decimal(str(args.multiplier))
            print(f"\npools x {args.multiplier:g}:")
            for key in POOL_KEYS:
                old = eps.get_param(db, key)
                new = (old * k).quantize(Decimal("1"))
                print(f"  {key:<34} ${old:>12,.0f} -> ${new:>12,.0f}")
                eps.set_param(db, key, new)
            print(f"\nprojected dividends per year: ~${dividends * args.multiplier:,.0f} "
                  f"= ~{dividends * args.multiplier / max(1.0, new_anchor) * 100:.1f}% of fair value (prices stay where they are)")

        if args.confirm:
            db.commit()
            fair_price_service.invalidate()
            print("\nSaved.")
        else:
            db.rollback()
            print("\nDRY RUN -- nothing was changed. Add --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
