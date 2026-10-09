#!/usr/bin/env python3
"""
READ-ONLY health check for the linker merge -- run it after scripts/merge_from_linker.py --confirm, and again
before every LAN event ("is everything ready?"). Nothing is written.

GLOBAL INTEGRITY (problems here can break future syncs or dividends)
  1. Epic-account mappings that point at a merged-away (tombstoned) player  -> a sync would attach results to a dead row
  2. Merged-away players that still hold placements / positions / orders / entrants / aliases  -> merge incomplete
  3. Active players whose names differ only by case/punctuation-insensitive skeleton  -> leftover duplicates
  4. Two players whose gamertags are equal ignoring case  -> _match_player's name lookup would raise on that name
  5. Active players with zero placements (not necessarily wrong, listed for review)
  6. Pro-named players that are inactive

PER-PRO (every row of the sheet)
  - resolves to exactly one live player by Epic ID (or, failing that, by alias/LAN name)
  - that player's gamertag == the sheet's "Pro Name (auto)"
  - every LAN account name of the pro is registered as an alias of that player
  - no OTHER live player carries one of the pro's LAN names or the pro name (leftover duplicate)

    python3 scripts/verify_linker.py
    python3 scripts/verify_linker.py --file other.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, PlayerAlias  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, TournamentEntrant  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402
from app.services.player_identity import norm_id, skeleton  # noqa: E402
from scripts.merge_from_linker import DEFAULT_FILE, build_groups, load_rows  # noqa: E402

_TOMB = "[MERGED INTO"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    args = ap.parse_args()
    from pathlib import Path

    groups = build_groups(load_rows(Path(args.file)))
    db = SessionLocal()
    db.expire_on_commit = False
    problems = 0
    try:
        players = db.query(Player).all()
        live = [p for p in players if not p.gamertag.startswith(_TOMB)]
        tombs = [p for p in players if p.gamertag.startswith(_TOMB)]
        by_id = {p.id: p for p in players}
        pcount = dict(db.query(PlacementResult.player_id, func.count(PlacementResult.id)).group_by(PlacementResult.player_id).all())
        print(f"players: {len(live)} live, {len(tombs)} merged-away tombstones\n")

        # 1. mappings -> tombstone
        bad_map = [m for m in db.query(OsirionPlayerMapping).all() if m.player_id in by_id and by_id[m.player_id].gamertag.startswith(_TOMB)]
        print(f"[1] Epic mappings pointing at a tombstoned player: {len(bad_map)}")
        for m in bad_map[:20]:
            print(f"      {m.osirion_account_id}  ({m.osirion_username})  -> {by_id[m.player_id].gamertag!r}")
        problems += len(bad_map)

        # 2. tombstones still holding data
        tomb_ids = [p.id for p in tombs]
        held = defaultdict(dict)
        if tomb_ids:
            for model, label in ((PlacementResult, "placements"), (Order, "orders"), (TournamentEntrant, "entrants"), (PlayerAlias, "aliases")):
                for pid, n in db.query(model.player_id, func.count()).filter(model.player_id.in_(tomb_ids)).group_by(model.player_id).all():
                    held[pid][label] = n
            for pid, n in db.query(Position.player_id, func.count()).filter(Position.player_id.in_(tomb_ids), Position.quantity > 0).group_by(Position.player_id).all():
                held[pid]["positions"] = n
        # placements left behind because they collided with the target's own are expected; report separately
        print(f"[2] Tombstones still holding rows: {len(held)}")
        for pid, d in list(held.items())[:25]:
            print(f"      {by_id[pid].gamertag!r}: {d}")
        problems += sum(1 for d in held.values() if set(d) - {"placements"})
        active_tomb = [p for p in tombs if p.is_active]
        print(f"    tombstones still ACTIVE (should be 0): {len(active_tomb)}")
        problems += len(active_tomb)

        # 3. skeleton duplicates
        sk = defaultdict(list)
        for p in live:
            if p.is_active:
                sk[skeleton(p.gamertag)].append(p)
        dupes = {k: v for k, v in sk.items() if len(v) > 1}
        tset = defaultdict(set)
        if dupes:
            ids = [p.id for v in dupes.values() for p in v]
            for pid, tid in db.query(PlacementResult.player_id, PlacementResult.tournament_id).filter(PlacementResult.player_id.in_(ids)).all():
                tset[pid].add(tid)
        real_dupes, distinct = {}, {}
        for k, v in dupes.items():
            shared = any(tset[a.id] & tset[b.id] for i, a in enumerate(v) for b in v[i + 1:])
            (distinct if shared else real_dupes)[k] = v
        print(f"\n[3] Active players sharing a name skeleton: {len(real_dupes)}")
        for k, v in list(real_dupes.items())[:30]:
            print("      " + "  |  ".join(f"{p.gamertag!r} ({pcount.get(p.id, 0)} pl)" for p in v))
        problems += len(real_dupes)
        if distinct:
            print(f"    look-alike names that placed in the SAME tournament (two different people -- fine, not merged): {len(distinct)}")
            for k, v in distinct.items():
                print("      " + "  |  ".join(f"{p.gamertag!r}" for p in v))

        # 4. case-insensitive gamertag equality
        ci = defaultdict(list)
        for p in live:
            ci[p.gamertag.strip().casefold()].append(p)
        ci_bad = {k: v for k, v in ci.items() if len(v) > 1}
        print(f"\n[4] Gamertags equal ignoring case (would break name matching): {len(ci_bad)}")
        for k, v in ci_bad.items():
            print("      " + "  |  ".join(repr(p.gamertag) for p in v))
        problems += len(ci_bad)

        zero = [p for p in live if p.is_active and not pcount.get(p.id)]
        print(f"\n[5] Active players with zero placements: {len(zero)}")
        for p in zero[:15]:
            print(f"      {p.gamertag!r}")

        # per pro
        maps = {norm_id(m.osirion_account_id): m for m in db.query(OsirionPlayerMapping).all()}
        aliases = {a.alias_key: a for a in db.query(PlayerAlias).all()}
        skeleton_to_live = defaultdict(list)
        for p in live:
            skeleton_to_live[skeleton(p.gamertag)].append(p)

        mapped_name = defaultdict(set)
        for m in maps.values():
            if m.osirion_username and m.player_id in by_id and not by_id[m.player_id].gamertag.startswith(_TOMB):
                mapped_name[skeleton(m.osirion_username)].add(m.player_id)
        print("\n[PER-PRO] checking sheet rows ...")
        pro_issues, ok, not_resolved = [], 0, []
        sheet_verified: set = set()
        inactive_pros = 0
        for g in groups:
            label = f"[{'/'.join(g['player_ids']) or '?'}] {g['pro']}"
            targets = {}
            for i in g["epic_ids"]:
                m = maps.get(norm_id(i))
                if m is not None and m.player_id in by_id and not by_id[m.player_id].gamertag.startswith(_TOMB):
                    targets[m.player_id] = by_id[m.player_id]
            via = "epic-id"
            if not targets:
                for n in g["names"]:
                    a = aliases.get(skeleton(n))
                    if a is not None and a.player_id in by_id:
                        targets[a.player_id] = by_id[a.player_id]
                    for p in skeleton_to_live.get(skeleton(n), []):
                        targets[p.id] = p
                    for pid in mapped_name.get(skeleton(n), ()):
                        targets[pid] = by_id[pid]
                via = "name/alias"
            if not targets:
                not_resolved.append(label)
                continue
            if len(targets) > 1:
                pro_issues.append(f"{label}: resolves to {len(targets)} different players: " + ", ".join(repr(p.gamertag) for p in targets.values()))
                continue
            t = next(iter(targets.values()))
            msgs = []
            if t.gamertag != g["pro"]:
                msgs.append(f"gamertag is {t.gamertag!r}, sheet says {g['pro']!r}")
            if not t.is_verified:
                msgs.append("not marked verified (run merge_from_linker.py --confirm)")
            sheet_verified.add(t.id)
            if not t.is_active:
                msgs.append("player is INACTIVE")
                inactive_pros += 1
            for n in g["names"]:
                a = aliases.get(skeleton(n))
                if a is None:
                    msgs.append(f"LAN name {clean_gamertag(n)!r} not registered as alias (run merge_from_linker.py --confirm)")
                elif a.player_id != t.id:
                    msgs.append(f"alias {clean_gamertag(n)!r} belongs to a different player")
                for p in skeleton_to_live.get(skeleton(n), []):
                    if p.id != t.id:
                        msgs.append(f"another live player {p.gamertag!r} carries LAN name {clean_gamertag(n)!r}")
            for p in skeleton_to_live.get(skeleton(g["pro"]), []):
                if p.id != t.id:
                    msgs.append(f"another live player {p.gamertag!r} carries the pro name")
            if msgs:
                pro_issues.append(f"{label} ({via}): " + "; ".join(msgs))
            else:
                ok += 1

        stray = [p for p in live if p.is_verified and p.id not in sheet_verified]
        if stray:
            pro_issues.append(f"{len(stray)} player(s) are marked verified but are not in the sheet (or not resolvable): "
                              + ", ".join(repr(p.gamertag) for p in stray[:10]))
        print(f"    OK: {ok}   with issues: {len(pro_issues)}   not resolvable (no ID mapping / alias / LAN-name player): {len(not_resolved)}")
        for line in pro_issues:
            print("      ! " + line)
        problems += len(pro_issues)
        if not_resolved:
            print("    not resolvable: " + ", ".join(not_resolved))
            print("    (run scripts/diagnose_missing_pros.py to see whether they appear in any synced leaderboard)")

        print("\n" + ("ALL CHECKS PASSED" if problems == 0 else f"{problems} problem(s) above need attention") +
              (f"   ({len(not_resolved)} pro(s) not in the database)" if not_resolved else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main()
