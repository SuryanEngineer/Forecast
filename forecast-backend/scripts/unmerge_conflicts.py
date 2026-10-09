#!/usr/bin/env python3
"""
Undo merges that should not have happened: a merged-away (tombstoned) player that STILL holds a placement.

merge_skeleton_dupes.py / _merge_player skip a placement when the survivor already has one in the same tournament. One
person can't place twice in a tournament, so such a pair is two DIFFERENT people with look-alike names (e.g. a Cyrillic
"е" in 'gamеslefthim'). verify_linker.py section [2] lists these tombstones.

For each one this restores the original player:
  * gamertag back to the original name (taken from the "[MERGED INTO x] original" tombstone text), re-activated
  * its Epic account mapping(s) moved back -- identified by the EXACT original name stored in
    OsirionPlayerMapping.osirion_username (case/characters must match, so the look-alike twin is never taken)
  * the placements that came from those accounts moved back (found via the account ids inside each placement's stored
    raw leaderboard entry)
Anything it cannot identify with certainty aborts that one restore and is reported. Dry run by default.

    python3 scripts/unmerge_conflicts.py
    python3 scripts/unmerge_conflicts.py --confirm
"""
from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402
from app.services.player_identity import norm_id  # noqa: E402

_TOMB = re.compile(r"^\[MERGED INTO (.*?)\] (.*)$", re.S)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    db.expire_on_commit = False
    try:
        tombs = db.query(Player).filter(Player.gamertag.startswith("[MERGED INTO")).all()
        holding = {pid for (pid,) in db.query(PlacementResult.player_id).filter(
            PlacementResult.player_id.in_([t.id for t in tombs])).distinct()} if tombs else set()
        todo = [t for t in tombs if t.id in holding]
        print(f"{len(todo)} merged-away player(s) still hold placements.\n")
        for t in todo:
            m = _TOMB.match(t.gamertag)
            if not m:
                print(f"{t.gamertag!r}: cannot parse the tombstone text -- skipped")
                continue
            target_name, orig = m.group(1), m.group(2)
            target = db.query(Player).filter(Player.gamertag == target_name).first()
            print("=" * 90)
            print(f"restore {orig!r}   (was merged into {target_name!r})")
            if target is None:
                print("  target player not found by that name -- skipped")
                continue
            if db.query(Player).filter(Player.gamertag == orig).first() is not None:
                print(f"  a player named {orig!r} already exists -- skipped")
                continue
            maps = [mp for mp in db.query(OsirionPlayerMapping).filter(OsirionPlayerMapping.player_id == target.id).all()
                    if mp.osirion_username is not None and clean_gamertag(mp.osirion_username) == orig]
            if not maps:
                print("  no Epic mapping with that exact original name on the target -- cannot identify its account; skipped")
                continue
            ids = {norm_id(mp.osirion_account_id) for mp in maps}
            back = []
            for pr in db.query(PlacementResult).filter(PlacementResult.player_id == target.id).all():
                entry = pr.raw_stats or {}
                accts = {norm_id(p.get("accountId") or "") for p in (entry.get("players") or [])}
                if accts & ids:
                    back.append(pr)
            # a team entry can list the target's own account too; only move rows whose entry has NO other account of the target
            target_ids = {norm_id(mp.osirion_account_id) for mp in db.query(OsirionPlayerMapping).filter(
                OsirionPlayerMapping.player_id == target.id).all()} - ids
            back = [pr for pr in back if not ({norm_id(p.get("accountId") or "") for p in (pr.raw_stats or {}).get("players", [])} & target_ids)]
            print(f"  mappings to move back: {len(maps)}   placements to move back: {len(back)}   (already on the restored row: "
                  f"{db.query(func.count(PlacementResult.id)).filter(PlacementResult.player_id == t.id).scalar()})")
            if not args.confirm:
                continue
            for mp in maps:
                mp.player_id = t.id
            for pr in back:
                pr.player_id = t.id
            t.gamertag = orig[:100]
            t.is_active = True
            db.commit()
            print("  restored.")
        if not args.confirm:
            print("\nDry run only. Re-run with --confirm.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
