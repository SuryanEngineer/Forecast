#!/usr/bin/env python3
"""
Read-only price audit: for the players with the biggest career dividend pools, shows listed price next to what the bots'
model thinks they are worth, so you can tell whether a mispricing is the MODEL (fair value is wrong) or PRICE DISCOVERY
(fair value is right but the market hasn't caught up).

    cd forecast-backend
    python3 scripts/price_audit.py            # top 30
    python3 scripts/price_audit.py --top 60

Columns: events = tournaments played, avg_pool = model's expected pool-share per event (recency-weighted),
career = sum over events of pool x payout-curve fraction, fair = skill-based fair value, model = fair adjusted for
outlook (form / upcoming event / qualifiers), price = listed price, gap = price / model.
Writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.engine.dividend_calculator import placement_payout_fraction  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult  # noqa: E402
from app.services import bot_trading_service as bts  # noqa: E402
from app.services import economic_params_service  # noqa: E402
from sqlalchemy import func  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        bts.reset_caches()
        snap = bts._build_snapshot(db)
        names = {pid: tag for pid, tag in db.query(Player.id, Player.gamertag).filter(Player.id.in_(snap.player_ids)).all()}
        ev, _, _, _ = bts._career_stats(db, snap.player_ids)

        rows = db.query(PlacementResult.player_id, PlacementResult.tournament_id, PlacementResult.placement).filter(PlacementResult.player_id.in_(snap.player_ids)).all()
        tids = {t for _, t, _ in rows}
        sizes = dict(db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(tids)).group_by(PlacementResult.tournament_id).all())
        pools = bts._tournament_pool_amounts(db, list(tids))
        curve = economic_params_service.get_placement_curve(db)
        career: dict = defaultdict(float)
        events: dict = defaultdict(int)
        for pid, tid, place in rows:
            career[pid] += float(pools.get(tid, 0)) * float(placement_payout_fraction(place, max(1, sizes.get(tid, 1)), curve))
            events[pid] += 1

        ranked = sorted(career, key=lambda p: career[p], reverse=True)[: args.top]
        print(f"base price (median IPO) = {snap.base_price}\n")
        print(f"{'player':<22}{'events':>7}{'avg_pool':>11}{'career':>12}{'fair':>9}{'model':>9}{'price':>9}{'gap':>7}")
        for pid in ranked:
            fair, model, price = float(snap.fair_value[pid]), float(snap.model_value[pid]), float(snap.price[pid])
            print(f"{names.get(pid, '?')[:21]:<22}{events[pid]:>7}{float(ev.get(pid, 0)):>11,.0f}{career[pid]:>12,.0f}{fair:>9.2f}{model:>9.2f}{price:>9.2f}{price / model:>7.2f}")

        # How well does price order players the way career earnings do?
        import statistics

        def ranks(vals):
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            r = [0] * len(vals)
            for k, i in enumerate(order):
                r[i] = k
            return r

        both = [p for p in career if p in snap.price]
        if len(both) > 3:
            a, b = ranks([career[p] for p in both]), ranks([float(snap.price[p]) for p in both])
            c = ranks([float(snap.fair_value[p]) for p in both])
            def corr(x, y):
                mx, my = statistics.mean(x), statistics.mean(y)
                num = sum((i - mx) * (j - my) for i, j in zip(x, y))
                den = (sum((i - mx) ** 2 for i in x) * sum((j - my) ** 2 for j in y)) ** 0.5
                return num / den if den else 0.0
            print(f"\nRank correlation with career earnings (1.0 = perfect): price {corr(a, b):.2f}   model fair value {corr(a, c):.2f}")
            print("  fair value high but price low  -> price discovery is behind (let bots run / kickstart).")
            print("  fair value itself low          -> the model is the problem.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
