#!/usr/bin/env python3
"""
READ-ONLY. Trace ONE pro end to end, to see exactly where the Epic-ID -> LAN name -> listed name chain connects or breaks.

For the pro it prints:
  1. the spreadsheet row(s): Epic ID, listed name, LAN names
  2. which player (if any) already holds each sheet Epic ID in OsirionPlayerMapping
  3. every player whose name looks like the pro (name contains / prefixed), with all Epic account IDs they hold
  4. every place the sheet's Epic ID(s) appear in the ARCHIVED raw leaderboards (tournament, the username used there,
     and which player that tournament's result row points at)

    python3 scripts/trace_pro.py SwizzY
    python3 scripts/trace_pro.py Peterbot
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentResultArchive  # noqa: E402
from app.services.player_identity import norm_id, skeleton  # noqa: E402
from scripts.merge_from_linker import DEFAULT_FILE, build_groups, load_rows  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    needle = sys.argv[1]
    rows = [r for r in load_rows(Path(DEFAULT_FILE)) if skeleton(r["pro"]) == skeleton(needle)]
    if not rows:
        sys.exit(f"No sheet row with pro name {needle!r}")
    db = SessionLocal()
    try:
        print("=" * 90)
        print("1. SHEET")
        sheet_ids = set()
        for r in rows:
            print(f"   {r['player_id']}  pro={r['pro']!r}  epic_id={r['epic_id']}  EWC={r['ewc']!r}  GC={r['gc']!r}  notes={r['notes']!r}")
            if r["epic_id"]:
                sheet_ids.add(norm_id(r["epic_id"]))

        maps = db.query(OsirionPlayerMapping).all()
        by_id = {norm_id(m.osirion_account_id): m for m in maps}
        print("\n2. WHO HOLDS EACH SHEET EPIC ID IN THE DATABASE")
        for sid in sheet_ids:
            m = by_id.get(sid)
            if m is None:
                print(f"   {sid}: NOT in osirion_player_mappings  (this account never appeared in a synced leaderboard)")
            else:
                p = db.get(Player, m.player_id)
                print(f"   {sid}: -> player {p.gamertag!r} (id {str(p.id)[:8]})  mapping username={m.osirion_username!r}")

        key = skeleton(needle)
        print(f"\n3. PLAYERS WHOSE NAME CONTAINS {needle!r}, WITH THEIR EPIC ACCOUNT IDS")
        ids_by_player = {}
        for m in maps:
            ids_by_player.setdefault(m.player_id, []).append(m)
        for p in db.query(Player).all():
            if key in skeleton(p.gamertag) or any(key in skeleton(m.osirion_username or "") for m in ids_by_player.get(p.id, [])):
                tag = " (SHEET ID!)" if any(norm_id(m.osirion_account_id) in sheet_ids for m in ids_by_player.get(p.id, [])) else ""
                print(f"   {p.gamertag!r}  id={str(p.id)[:8]}  active={p.is_active}  verified={p.is_verified}{tag}")
                for m in ids_by_player.get(p.id, []):
                    print(f"        epic {m.osirion_account_id}  username-seen={m.osirion_username!r}")

        print("\n4. WHERE THE SHEET EPIC ID APPEARS IN ARCHIVED RAW LEADERBOARDS")
        found = 0
        tn = {t.id: t for t in db.query(Tournament).all()}
        for arch in db.query(TournamentResultArchive).all():
            t = tn.get(arch.tournament_id)
            for entry in arch.raw_leaderboard_entries or []:
                for pl in entry.get("players", []):
                    if norm_id(pl.get("accountId") or "") in sheet_ids:
                        found += 1
                        res = (
                            db.query(PlacementResult, Player)
                            .join(Player, Player.id == PlacementResult.player_id)
                            .filter(PlacementResult.tournament_id == arch.tournament_id, PlacementResult.placement == entry.get("rank"))
                            .all()
                        )
                        names = ", ".join(repr(p.gamertag) for _, p in res) or "(no result row)"
                        print(f"   {t.name if t else arch.tournament_id}: rank {entry.get('rank')}  username={pl.get('username')!r}  -> result rows for that rank: {names}")
        if not found:
            print("   (the sheet's Epic ID does not appear in any archived leaderboard)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
