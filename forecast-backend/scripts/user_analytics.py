#!/usr/bin/env python3
"""
User analytics report: every real account (bots and the House excluded) with sign-up date, last seen, logins,
sessions, minutes on site, orders/trades/volume, dividends, fees, net worth, return % and season rank -- plus
headline KPIs (sign-ups, DAU/WAU/MAU, % who ever traded, % returning, % verified).

    cd forecast-backend
    python3 scripts/user_analytics.py                  # KPIs + top of the table in the terminal, CSV saved
    python3 scripts/user_analytics.py --top 50         # show 50 rows instead of 25
    python3 scripts/user_analytics.py --sort trades    # sort by: created|last_seen|minutes|trades|volume|net_worth|return
    python3 scripts/user_analytics.py --no-csv

The CSV (analytics/users_<timestamp>.csv) has every account and opens in Excel. Read-only: changes nothing.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.services import analytics_service  # noqa: E402

SORTS = {
    "created": ("created_at", False), "last_seen": ("last_seen", True), "minutes": ("minutes_on_site", True),
    "trades": ("trades", True), "volume": ("trade_volume", True), "net_worth": ("net_worth", True), "return": ("return_pct", True),
}


def _fmt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "" if v is None else str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--sort", choices=SORTS.keys(), default="created")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = analytics_service.user_table(db)
        k = analytics_service.kpis(db, rows)
        db.rollback()  # read-only (season_standings may stage entries; never persist from a report)
    finally:
        db.close()

    print("\n=== FORECAST USER ANALYTICS ===", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    print(f"Accounts: {k['total_users']}   (+{k['signups_24h']} in 24h, +{k['signups_7d']} in 7d, +{k['signups_30d']} in 30d)")
    print(f"Active (last seen): 24h={k['active_24h']}  7d={k['active_7d']}  30d={k['active_30d']}")
    print(f"Ever traded: {k['pct_ever_traded']}%   Came back (2+ sessions): {k['pct_returning']}%   Email verified: {k['pct_email_verified']}%")
    print(f"Total trades: {k['total_trades']}   Time on site: {k['total_minutes_on_site']} min total, {k['avg_minutes_per_user']} min/user, {k['avg_sessions_per_user']} sessions/user")
    if k["daily_active_last_14d"]:
        print("Daily active users (last 14d): " + "  ".join(f"{d[5:]}:{n}" for d, n in k["daily_active_last_14d"].items()))
    if k["signups_last_14d"]:
        print("Sign-ups per day (last 14d):   " + "  ".join(f"{d[5:]}:{n}" for d, n in k["signups_last_14d"].items()))

    key, desc = SORTS[args.sort]
    rows.sort(key=lambda r: (r[key] is None, r[key] or 0), reverse=desc)
    cols = ["username", "email", "created_at", "last_seen", "sessions", "minutes_on_site", "trades", "trade_volume",
            "dividends", "net_worth", "return_pct", "season_rank", "email_verified"]
    print(f"\nTop {min(args.top, len(rows))} by {args.sort}:")
    widths = {c: max(len(c), *(len(_fmt(r[c])) for r in rows[:args.top])) if rows else len(c) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows[:args.top]:
        print("  ".join(_fmt(r[c]).ljust(widths[c]) for c in cols))

    if not args.no_csv and rows:
        os.makedirs("analytics", exist_ok=True)
        path = os.path.join("analytics", f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k2: _fmt(v) if isinstance(v, datetime) else v for k2, v in r.items()})
        print(f"\nFull table ({len(rows)} accounts) saved to {path}")


if __name__ == "__main__":
    main()
