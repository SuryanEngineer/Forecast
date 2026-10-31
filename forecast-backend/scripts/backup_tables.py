#!/usr/bin/env python3
"""
Saves the tables the price reset changes (orders, wallets, players) to CSV files on THIS computer, so the reset can be undone.
The free Supabase plan has no backups, so run this right before simulate_price_history.py --reset-prices --yes.

    cd forecast-backend
    python3 scripts/backup_tables.py              # writes backups/<timestamp>/orders.csv, wallets.csv, players.csv
    python3 scripts/backup_tables.py --restore backups/<timestamp> --yes

What a restore puts back (nothing else is touched): every order's limit price, status and cancelled time; every wallet's cash and
held balance; every player's reference price. It does NOT restore deleted price history (that is synthetic: re-run
simulate_price_history.py). Suspend the backend before restoring, and restart it afterwards.
The backups folder holds user data and is git-ignored. Never commit or share it.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402

TABLES = ["orders", "wallets", "players"]
# Columns a restore writes back, per table (primary key is "id").
RESTORE_COLUMNS = {
    "orders": ["limit_price", "status", "cancelled_at"],
    "wallets": ["cash_balance", "held_balance"],
    "players": ["reference_price"],
}


def backup(db) -> Path:
    out = Path("backups") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        res = db.execute(text(f"SELECT * FROM {t}"))
        cols = list(res.keys())
        n = 0
        with open(out / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in res:
                w.writerow(["" if v is None else v for v in row])
                n += 1
        print(f"  {t}: {n:,} rows -> {out / (t + '.csv')}")
    print(f"\nBackup saved in {out.resolve()}")
    return out


def restore(db, folder: Path, yes: bool) -> None:
    if not yes:
        print("Refusing to restore without --yes (this overwrites the columns listed in the file's docstring).")
        return
    from app.services import lease_service

    lease_service.script_guard_or_exit(db, "backup_tables --restore")
    for t, cols in RESTORE_COLUMNS.items():
        path = folder / f"{t}.csv"
        n = 0
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sets = ", ".join(f"{c} = :{c}" for c in cols)
                params = {c: (row[c] if row[c] != "" else None) for c in cols}
                params["id"] = row["id"]
                if t == "orders":
                    sets = "limit_price = :limit_price, status = CAST(:status AS order_status), cancelled_at = :cancelled_at"
                db.execute(text(f"UPDATE {t} SET {sets} WHERE id = :id"), params)
                n += 1
                if n % 1000 == 0:
                    db.commit()
        db.commit()
        print(f"  restored {n:,} {t} rows")
    print("Done. Restart the backend so it rebuilds its order books and price cache.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restore", default=None, help="Folder to restore from, e.g. backups/20261031-120000")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.restore:
            restore(db, Path(args.restore), args.yes)
        else:
            backup(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
