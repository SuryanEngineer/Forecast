#!/usr/bin/env python3
"""
STEP 1 OF 2 of a full roster reset: back up, then WIPE every Player row (and,
through the database's ON DELETE CASCADE, everything attached to a player:
Osirion account mappings, placements, dividend payouts, positions, orders,
trades, auction listings, price history). Step 2 is scripts/resync_roster.py,
which re-pulls every tracked tournament from Osirion and rebuilds the roster
and every placement from scratch -- with no merges, no tombstones, and every
Osirion account id freshly mapped.

Use this when you want "as if we had never merged anything".

WHAT IS AND ISN'T TOUCHED
  Wiped (cascade):   players, osirion_player_mappings, placement_results,
                     dividend_payouts (+ line items), positions, orders, trades,
                     auction listings, player price history, tournament entrants.
  NOT touched:       users, wallets/cash balances, bot profiles, the House account,
                     tournaments and their Osirion window mappings, the raw
                     leaderboard archive, classification rules.
  Consequences you should expect:
    * Bots/House lose their share positions; players are re-created by step 2 with
      fresh IPO share pools owned by House, and bots re-trade from there.
    * Any REAL user's holdings, open orders and trade/dividend history against
      players disappear with the players, and their CASH IS NOT REFUNDED (what they
      paid for shares and any dividends they already received stay as they are).
      That is why this script refuses to run if real users have any such data,
      unless you pass --allow-real-user-data.
    * Finalized tournaments that have NO Osirion mapping (manually entered) cannot be
      re-pulled, so their results would be lost. The script refuses unless you pass
      --allow-unmapped-loss.

BEFORE YOU RUN IT FOR REAL
    * Stop the deployed backend (or at least its background loops) while resetting --
      the bot-tick and Osirion sync loops would otherwise run against a half-empty
      database.
    * Supabase free tier has no automatic backups. This script writes its own CSV
      snapshot (players, mappings, placements, payouts, positions) to --export-dir
      first and refuses to wipe if that export fails. It is a record of the data, not a
      one-click restore. For a real restore point also run pg_dump yourself, e.g.
        pg_dump "<your DATABASE_URL>" -Fc -f forecast_before_reset.dump

Everything is a dry run (counts only, nothing written) unless you pass --confirm,
and --confirm additionally makes you type RESET ROSTER.

Usage:
    cd forecast-backend
    python3 scripts/reset_roster.py                    # dry run: what would be wiped
    python3 scripts/reset_roster.py --confirm          # export, then wipe
    python3 scripts/resync_roster.py                   # step 2: rebuild from Osirion
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import exists, func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.order import Order, Trade  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, OsirionTournamentMapping  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402
from scripts.merge_fuzzy_duplicates import _TOMBSTONE_PREFIX, _real_user_ids  # noqa: E402

STATE_FILE = Path("roster_reset_state.json")
_DELETE_CHUNK = 1000
_PHRASE = "RESET ROSTER"


def _dump_table(db, model, path: Path) -> int:
    table = model.__table__
    cols = [c.name for c in table.columns]
    rows = db.execute(table.select()).fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in rows:
            writer.writerow(["" if v is None else str(v) for v in row])
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="Export a snapshot, then wipe. Without it: dry run.")
    parser.add_argument("--export-dir", type=Path, default=None, help="Where to write the CSV snapshot "
                        "(default: roster_backup_<timestamp> in the current directory).")
    parser.add_argument("--allow-real-user-data", action="store_true",
                        help="Proceed even though real users hold/ordered/traded/were paid by players (their cash is NOT refunded).")
    parser.add_argument("--allow-unmapped-loss", action="store_true",
                        help="Proceed even though some finalized tournaments have no Osirion mapping and can't be re-pulled.")
    args = parser.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        real_user_ids = _real_user_ids(db)

        n_players = db.query(func.count(Player.id)).scalar()
        n_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar()
        n_tomb = db.query(func.count(Player.id)).filter(Player.gamertag.startswith(_TOMBSTONE_PREFIX)).scalar()
        n_maps = db.query(func.count(OsirionPlayerMapping.id)).scalar()
        n_place = db.query(func.count(PlacementResult.id)).scalar()
        n_pay = db.query(func.count(DividendPayout.id)).scalar()

        finalized_mapped = (
            db.query(Tournament)
            .filter(Tournament.status == TournamentStatus.FINALIZED)
            .filter(exists().where(OsirionTournamentMapping.tournament_id == Tournament.id))
            .order_by(Tournament.start_time.asc().nullslast())
            .all()
        )
        finalized_unmapped = (
            db.query(Tournament)
            .filter(Tournament.status == TournamentStatus.FINALIZED)
            .filter(~exists().where(OsirionTournamentMapping.tournament_id == Tournament.id))
            .all()
        )

        real_positions = (
            db.query(func.count(Position.id)).filter(Position.quantity > 0, Position.user_id.in_(real_user_ids)).scalar()
            if real_user_ids else 0
        )
        real_orders = db.query(func.count(Order.id)).filter(Order.user_id.in_(real_user_ids)).scalar() if real_user_ids else 0
        real_dividends = (
            db.query(func.count(DividendLineItem.id)).filter(DividendLineItem.user_id.in_(real_user_ids)).scalar()
            if real_user_ids else 0
        )
        real_trades = (
            db.query(func.count(Trade.id))
            .filter((Trade.buyer_user_id.in_(real_user_ids)) | (Trade.seller_user_id.in_(real_user_ids)))
            .scalar()
            if real_user_ids else 0
        )

        print("WOULD WIPE (via cascade):")
        print(f"  players: {n_players}  (active {n_active}, merged-away tombstones {n_tomb})")
        print(f"  osirion player mappings: {n_maps}   placement results: {n_place}   dividend payouts: {n_pay}")
        print("\nWOULD BE RE-PULLED FROM OSIRION by step 2:")
        print(f"  {len(finalized_mapped)} finalized tournament(s) with an Osirion mapping")
        print("\nREAL-USER EXPOSURE (real = not a bot, not House); cash is NOT refunded for any of this:")
        print(f"  open share positions: {real_positions}   orders: {real_orders}   dividend payouts received: "
              f"{real_dividends}   trades: {real_trades}")
        print(f"\nFinalized tournaments with NO Osirion mapping (results would be LOST): {len(finalized_unmapped)}")
        for t in finalized_unmapped[:20]:
            print(f"    - {t.name!r} ({t.start_time.date() if t.start_time else 'no date'})")

        exposure = real_positions + real_orders + real_dividends + real_trades
        if not args.confirm:
            print("\nDry run only -- nothing changed. Re-run with --confirm to export a snapshot and wipe.")
            if exposure:
                print("NOTE: real users have data against players, so --confirm will also need --allow-real-user-data.")
            if finalized_unmapped:
                print("NOTE: unmapped finalized tournaments exist, so --confirm will also need --allow-unmapped-loss.")
            return

        if exposure and not args.allow_real_user_data:
            sys.exit("\nREFUSING: real users have holdings/orders/trades/dividends against players. Wiping removes them "
                     "WITHOUT refunding cash. Re-run with --allow-real-user-data if that is acceptable.")
        if finalized_unmapped and not args.allow_unmapped_loss:
            sys.exit("\nREFUSING: some finalized tournaments have no Osirion mapping and cannot be re-pulled. "
                     "Re-run with --allow-unmapped-loss if that is acceptable.")
        if input(f"\nThis permanently deletes {n_players} players and everything attached to them. "
                 f"Type {_PHRASE} to continue: ").strip() != _PHRASE:
            sys.exit("Not confirmed -- nothing changed.")

        export_dir = args.export_dir or Path(f"roster_backup_{datetime.now():%Y%m%d_%H%M%S}")
        export_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nExporting a snapshot to {export_dir.resolve()} ...")
        for model, name in ((Player, "players"), (OsirionPlayerMapping, "osirion_player_mappings"),
                            (PlacementResult, "placement_results"), (DividendPayout, "dividend_payouts"),
                            (Position, "positions")):
            count = _dump_table(db, model, export_dir / f"{name}.csv")
            print(f"  {name}.csv: {count} row(s)")

        STATE_FILE.write_text(json.dumps({
            "created": datetime.now().isoformat(),
            "export_dir": str(export_dir.resolve()),
            "tournaments": [
                {"id": str(t.id), "name": t.name, "start_time": t.start_time.isoformat() if t.start_time else None,
                 "was_historical_archive": bool(t.is_historical_archive)}
                for t in finalized_mapped
            ],
            "done": [],
        }, indent=2), encoding="utf-8")
        print(f"Wrote {STATE_FILE.resolve()} (step 2 reads it to know which tournaments to re-pull).")

        ids = [r[0] for r in db.query(Player.id).all()]
        print(f"\nDeleting {len(ids)} player(s) in chunks of {_DELETE_CHUNK} ...")
        deleted = 0
        for i in range(0, len(ids), _DELETE_CHUNK):
            chunk = ids[i:i + _DELETE_CHUNK]
            db.query(Player).filter(Player.id.in_(chunk)).delete(synchronize_session=False)
            db.commit()
            deleted += len(chunk)
            print(f"  {deleted}/{len(ids)}")
        print("\nRoster wiped. Next: python3 scripts/resync_roster.py")
    finally:
        db.close()


if __name__ == "__main__":
    main()
