#!/usr/bin/env python3
"""
Read-only health check of the whole economy: does money supply, share supply, prices and dividends fit together?

Prints
  1. who holds the money (humans / bots / House) and how much is cash vs shares vs treasury,
  2. who holds the shares (how much of the float is still with the House),
  3. market cap vs the money that could actually buy it,
  4. price spread across the roster,
  5. dividend yield: what each stock pays per year (estimated from this year's results and the real payout pools)
     against its price, and how closely price follows dividends.

Nothing is written. Usage (from forecast-backend):
    python3 scripts/economy_check.py
    python3 scripts/economy_check.py --target-yield 0.08
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine.dividend_calculator import placement_payout_fraction  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.models.treasury import TreasuryHolding, TreasuryHoldingStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import Wallet  # noqa: E402
from app.services import bot_trading_service as bots  # noqa: E402
from app.services import economic_params_service, portfolio_service  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402


def money(x: float) -> str:
    return f"${x:,.0f}"


def pct(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))] if sorted_vals else 0.0


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    if len(xs) < 3:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-yield", type=float, default=0.08, help="Yearly dividend yield a fairly priced stock should offer (default 8%%).")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        house_id = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).scalar()
        bot_ids = {uid for (uid,) in db.query(BotProfile.user_id).all()}
        users = {uid for (uid,) in db.query(User.id).filter(User.is_active.is_(True)).all()}
        human_ids = users - bot_ids - ({house_id} if house_id else set())

        def group(uid):
            return "house" if uid == house_id else "bot" if uid in bot_ids else "human"

        cash = defaultdict(float)
        for uid, c in db.query(Wallet.user_id, Wallet.cash_balance).all():
            cash[group(uid)] += float(c)
        treasury = defaultdict(float)
        for uid, p, a in db.query(TreasuryHolding.user_id, TreasuryHolding.principal_amount, TreasuryHolding.accrued_interest).filter(TreasuryHolding.status == TreasuryHoldingStatus.ACTIVE).all():
            treasury[group(uid)] += float(p + a)

        players = db.query(Player.id, Player.gamertag, Player.total_shares_outstanding).filter(Player.is_active.is_(True)).all()
        pids = {p.id for p in players}
        shares = {p.id: p.total_shares_outstanding for p in players}
        price = {pid: float(px) for pid, px in portfolio_service.last_prices(db).items() if pid in pids}

        held = defaultdict(lambda: defaultdict(int))  # group -> player -> qty
        for uid, pid, qty in db.query(Position.user_id, Position.player_id, Position.quantity).filter(Position.quantity > 0).all():
            if pid in pids:
                held[group(uid)][pid] += qty
        value = {g: sum(price.get(pid, 0) * q for pid, q in d.items()) for g, d in held.items()}
        qty_total = {g: sum(d.values()) for g, d in held.items()}
        total_shares = sum(shares.values())
        mcap = sum(price.get(pid, 0) * shares[pid] for pid in shares)

        print("=" * 72)
        print(f"Users: {len(human_ids)} humans, {len(bot_ids)} bots, House {'yes' if house_id else 'no'}; {len(players)} active players")
        print("\n1. MONEY")
        for g in ("human", "bot", "house"):
            tot = cash[g] + treasury[g] + value.get(g, 0)
            print(f"   {g:<6} cash {money(cash[g]):>16}   treasury {money(treasury[g]):>14}   shares worth {money(value.get(g, 0)):>16}   = {money(tot):>16}")
        user_cash = cash["human"] + cash["bot"]
        user_value = value.get("human", 0) + value.get("bot", 0)
        user_wealth = user_cash + treasury["human"] + treasury["bot"] + user_value
        print(f"   players' total wealth (humans+bots): {money(user_wealth)}; {user_value / user_wealth * 100 if user_wealth else 0:.0f}% of it is in shares, {user_cash / user_wealth * 100 if user_wealth else 0:.0f}% idle cash")

        print("\n2. SHARES")
        user_qty = qty_total.get("human", 0) + qty_total.get("bot", 0)
        print(f"   total shares {total_shares:,}; held by players {user_qty:,} ({user_qty / total_shares * 100 if total_shares else 0:.1f}%); House holds {qty_total.get('house', 0):,} ({qty_total.get('house', 0) / total_shares * 100 if total_shares else 0:.1f}%)")
        print("   (the House sells to anyone at the going price, so supply never runs out)")

        print("\n3. MARKET CAP vs MONEY")
        print(f"   market cap (every share x price): {money(mcap)}")
        print(f"   = {mcap / user_wealth if user_wealth else 0:.1f}x all player wealth; players own {user_value / mcap * 100 if mcap else 0:.1f}% of the cap")
        print(f"   House cash {money(cash['house'])}, House share inventory {money(value.get('house', 0))}")

        pv = sorted(price.values())
        print("\n4. PRICES")
        print("   p5 ${:.2f}  p25 ${:.2f}  median ${:.2f}  p75 ${:.2f}  p95 ${:.2f}  max ${:.2f}".format(pct(pv, .05), pct(pv, .25), pct(pv, .5), pct(pv, .75), pct(pv, .95), pv[-1] if pv else 0))
        print(f"   under $5: {sum(1 for v in pv if v < 5)}   over $200: {sum(1 for v in pv if v > 200)}")

        # ---- dividends ----------------------------------------------------------------------------------------
        year = datetime.now(timezone.utc).year
        t0 = datetime(year, 1, 1, tzinfo=timezone.utc)
        days = max(30.0, (datetime.now(timezone.utc) - t0).total_seconds() / 86400.0)
        rows = (
            db.query(PlacementResult.player_id, PlacementResult.tournament_id, PlacementResult.placement)
            .join(Tournament, Tournament.id == PlacementResult.tournament_id)
            .filter(Tournament.start_time >= t0, PlacementResult.player_id.in_(pids))
            .all()
        )
        tids = {r[1] for r in rows}
        field = {tid: n for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(tids)).group_by(PlacementResult.tournament_id).all()}
        pools = bots._tournament_pool_amounts(db, list(tids))
        curve = economic_params_service.get_placement_curve(db)
        earned = defaultdict(float)
        for pid, tid, placement in rows:
            earned[pid] += float(pools.get(tid, Decimal(0)) * placement_payout_fraction(placement, max(1, field.get(tid, 1)), curve))
        scale = 365.0 / days
        per_share_year = {pid: earned[pid] * scale / shares[pid] for pid in earned if shares.get(pid)}
        total_year = sum(earned.values()) * scale
        print(f"\n5. DIVIDENDS (this year's results, scaled to 12 months; {len(tids)} tournaments, {days:.0f} days so far)")
        print(f"   dividends created per year: {money(total_year)} = {total_year / user_wealth * 100 if user_wealth else 0:.1f}% of player wealth, {total_year / mcap * 100 if mcap else 0:.2f}% of market cap")
        print(f"   starting balance per new user: {money(float(economic_params_service.get_param(db, 'wallet.starting_balance')))}; treasury pays about 1% a year, so a stock should pay clearly more to be worth holding")
        ys = []
        pairs = []
        for pid, dps in per_share_year.items():
            px = price.get(pid, 0)
            if px > 0:
                ys.append(dps / px)
                pairs.append((px, dps))
        ys.sort()
        if ys:
            print(f"   yearly dividend yield at today's prices: p10 {pct(ys, .1) * 100:.2f}%  median {pct(ys, .5) * 100:.2f}%  p90 {pct(ys, .9) * 100:.2f}%  max {ys[-1] * 100:.1f}%")
            print(f"   rank correlation, price vs yearly dividend per share: {spearman([a for a, _ in pairs], [b for _, b in pairs]):.2f} (1.0 = price follows dividends perfectly)")
            implied = {pid: dps / args.target_yield for pid, dps in per_share_year.items()}
            ratios = sorted(price[pid] / implied[pid] for pid in implied if implied[pid] > 0 and pid in price)
            print(f"   price / dividend-implied price at a {args.target_yield * 100:.0f}% yield: p10 {pct(ratios, .1):.2f}x  median {pct(ratios, .5):.2f}x  p90 {pct(ratios, .9):.2f}x (1.0x = priced exactly by dividends)")
            name = {p.id: p.gamertag for p in players}
            print("\n   top 8 by yearly dividend per share:")
            for pid, dps in sorted(per_share_year.items(), key=lambda kv: -kv[1])[:8]:
                px = price.get(pid, 0)
                print(f"     {name[pid]:<24} pays ${dps:>8.2f}/share/yr   price ${px:>8.2f}   yield {dps / px * 100 if px else 0:>6.1f}%   implied ${dps / args.target_yield:>8.2f}")
            print("   top 8 by price:")
            for pid, px in sorted(price.items(), key=lambda kv: -kv[1])[:8]:
                dps = per_share_year.get(pid, 0.0)
                print(f"     {name[pid]:<24} price ${px:>8.2f}   pays ${dps:>8.2f}/share/yr   yield {dps / px * 100 if px else 0:>6.1f}%")
        print("=" * 72)
    finally:
        db.close()


if __name__ == "__main__":
    main()
