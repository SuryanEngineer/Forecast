#!/usr/bin/env python3
"""
Merge active players whose names are the SAME once cosmetic differences are ignored (accents, look-alike letters,
case, punctuation, the decorative "ǃ" vs "!"): e.g. 'tyt nvtylerh' / 'tyt nvtylerhǃ', 'M8 Kurαma' / 'M8 kurama'.
These are the same display name written two ways, so they are the same person; the one with the most placements survives.
(This is the exact check verify_linker.py's section [3] reports.)

For each group it also prints, as a HINT only, any other live player whose name merely STARTS WITH the group's name
(e.g. 'falcon pollo' vs 'falcon pollo 10ǃ') -- those could be the same person too, but nothing is merged on a prefix.

Safety is the same as every other merge script (_why_unsafe_to_merge_away / _merge_player: nothing a real user holds,
ordered or traded is touched; colliding placements are skipped and reported; the loser is tombstoned and deactivated,
and its Epic account mappings move to the survivor so future syncs attach to the right player).

Dry run by default.

    python3 scripts/merge_skeleton_dupes.py
    python3 scripts/merge_skeleton_dupes.py --confirm

Manual pairs (exact gamertags; when given, ONLY these are processed). The dry run shows how many tournaments the two
players share -- a real person can't place twice in one tournament, so any overlap means "probably NOT the same person":
    python3 scripts/merge_skeleton_dupes.py --merge "falcon pollo=>Pollo" --merge "T1 demus=>Demus"
    python3 scripts/merge_skeleton_dupes.py --merge "falcon pollo=>Pollo" --confirm
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult  # noqa: E402
from app.services.player_identity import skeleton  # noqa: E402
from scripts.merge_fuzzy_duplicates import (  # noqa: E402
    _TOMBSTONE_PREFIX,
    _merge_player,
    _real_user_ids,
    _why_unsafe_to_merge_away,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--merge", action="append", default=[], metavar="SOURCE=>TARGET",
                    help="Merge the player with this exact gamertag into the other. Repeatable.")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        live = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).filter(Player.is_active.is_(True)).all()
        pcount = dict(db.query(PlacementResult.player_id, func.count(PlacementResult.id)).group_by(PlacementResult.player_id).all())
        sk = defaultdict(list)
        for p in live:
            sk[skeleton(p.gamertag)].append(p)
        if args.merge:
            by_tag = {p.gamertag: p for p in live}
            real = _real_user_ids(db)
            done = 0
            for spec in args.merge:
                if "=>" not in spec:
                    print(f"Bad --merge {spec!r}: use SOURCE=>TARGET")
                    continue
                a, b = (x.strip() for x in spec.split("=>", 1))
                src, tgt = by_tag.get(a), by_tag.get(b)
                if src is None or tgt is None or src.id == tgt.id:
                    print(f"{spec}: could not find both players by exact active gamertag (source found: {src is not None}, target found: {tgt is not None})")
                    continue
                s_t = {r[0] for r in db.query(PlacementResult.tournament_id).filter(PlacementResult.player_id == src.id)}
                t_t = {r[0] for r in db.query(PlacementResult.tournament_id).filter(PlacementResult.player_id == tgt.id)}
                overlap = len(s_t & t_t)
                print(f"{src.gamertag!r} ({len(s_t)} pl) => {tgt.gamertag!r} ({len(t_t)} pl)   shared tournaments: {overlap}"
                      + ("   <-- OVERLAP: probably two different people" if overlap else ""))
                if not args.confirm:
                    continue
                if overlap:
                    print("  SKIPPED (overlap).")
                    continue
                reason = _why_unsafe_to_merge_away(db, src.id, real)
                if reason is not None:
                    print(f"  SKIPPED: {reason}")
                    continue
                r = _merge_player(db, src, tgt)
                done += 1
                print(f"  merged: {r['mappings_moved']} mapping(s), {r['placements_moved']} placement(s) moved")
            print("\n" + (f"Merged {done}." if args.confirm else "Dry run only. Re-run with --confirm."))
            return
        groups = {k: v for k, v in sk.items() if len(v) > 1}
        print(f"{len(groups)} group(s) of active players with the same name skeleton.\n")
        real = _real_user_ids(db)

        merged = skipped = 0
        for k, members in sorted(groups.items()):
            members.sort(key=lambda p: (pcount.get(p.id, 0), p.is_active), reverse=True)
            target, losers = members[0], members[1:]
            print("=" * 90)
            print(f"TARGET  {target.gamertag!r}  placements={pcount.get(target.id, 0)}")
            for p in losers:
                print(f"  MERGE IN  {p.gamertag!r}  placements={pcount.get(p.id, 0)}")
            if not k.startswith("raw:"):
                hints = [p for p in live if p.id not in {m.id for m in members} and skeleton(p.gamertag).startswith(k) and len(k) >= 4]
                for h in hints[:5]:
                    print(f"  hint (not merged): {h.gamertag!r} starts with the same name  placements={pcount.get(h.id, 0)}")
            if not args.confirm:
                continue
            for p in losers:
                reason = _why_unsafe_to_merge_away(db, p.id, real)
                if reason is not None:
                    print(f"  SKIPPED {p.gamertag!r}: {reason}")
                    skipped += 1
                    continue
                s = _merge_player(db, p, target)
                merged += 1
                print(f"  merged {p.gamertag!r}: {s['mappings_moved']} mapping(s), {s['placements_moved']} placement(s) moved "
                      f"({s['placements_conflicted']} skipped as duplicate tournament)")
        print("\n" + ("Merged %d, skipped %d." % (merged, skipped) if args.confirm else "Dry run only. Re-run with --confirm to merge."))
    finally:
        db.close()


if __name__ == "__main__":
    main()
