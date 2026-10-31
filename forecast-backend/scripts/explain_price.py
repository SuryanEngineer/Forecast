#!/usr/bin/env python3
"""
READ-ONLY. Explains WHY a player is priced where they are: every tracked result with the dividend value it is worth, how much
of it falls in the last 12 months, how it is shrunk toward the typical player, and the resulting fair price.

    cd forecast-backend
    python3 scripts/explain_price.py Shxrk Peterbot Pollo

Use it to settle "should A be above B?": the model only knows results our database has (early 2026 onward), so a player whose big
wins came before that is priced lower than their real reputation. Writes nothing.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine.dividend_calculator import placement_payout_fraction  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.services import bot_trading_service as bots  # noqa: E402
from app.services import economic_params_service, fair_price_service  # noqa: E402


def _aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def main() -> None:
    names = sys.argv[1:]
    if not names:
        print(__doc__)
        return
    db = SessionLocal()
    try:
        y = fair_price_service.refresh_target_yield(db)
        now = datetime.now(timezone.utc)
        inc, _shares = fair_price_service.income_per_share(db)
        curve = economic_params_service.get_placement_curve(db)
        cutoff = now - timedelta(days=bots.INCOME_WINDOW_DAYS)
        print(f"target yield {y * 100:.2f}%   (fair price = shrunk yearly dividends per share / yield, floor ${bots.FAIR_MIN:g}, cap ${bots.FAIR_MAX:g})\n")
        for tag in names:
            p = db.query(Player).filter(func.lower(Player.gamertag) == tag.lower()).first()
            if p is None:
                print(f"{tag}: no such player\n")
                continue
            rows = (
                db.query(PlacementResult.placement, PlacementResult.tournament_id, Tournament.name, Tournament.tournament_type, Tournament.start_time, Tournament.end_time)
                .join(Tournament, Tournament.id == PlacementResult.tournament_id)
                .filter(PlacementResult.player_id == p.id, Tournament.start_time.isnot(None))
                .order_by(Tournament.start_time)
                .all()
            )
            tids = {r[1] for r in rows}
            field = {tid: n for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(tids)).group_by(PlacementResult.tournament_id).all()} if tids else {}
            pools = bots._tournament_pool_amounts(db, list(tids)) if tids else {}
            print(f"== {p.gamertag}   shares {p.total_shares_outstanding:,}   {len(rows)} tracked results")
            total = window = 0.0
            for placement, tid, name, ttype, start, end in rows:
                start = _aware(start)
                done = min(_aware(end) if end is not None else start + timedelta(days=1), now)
                frac = placement_payout_fraction(placement, max(1, field.get(tid, 1)), curve)
                value = float(pools.get(tid, Decimal("0")) * frac)
                total += value
                in_window = done > cutoff
                window += value if in_window else 0.0
                print(f"   {start.date()}  #{placement:<4} of {field.get(tid, '?'):<5} {str(ttype.value if hasattr(ttype, 'value') else ttype):<20} pool ${float(pools.get(tid, 0)):>10,.0f} x {float(frac):.4f} = ${value:>10,.0f}{'' if in_window else '  (older than 12 months)'}  {name[:40]}")
            s = max(1, p.total_shares_outstanding)
            print(f"   total dividend value ${total:,.0f}; last 12 months ${window:,.0f}")
            if p.id in inc:
                per = inc[p.id]
                print(f"   shrunk projected yearly dividends/share ${per:,.2f} -> fair price ${float(bots._fair_from_income(per)):,.2f}   (stock-wide ${per * s:,.0f} a year)\n")
            else:
                print("   no results history -> no fair price (priced near the floor)\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
