#!/usr/bin/env python3
"""
READ-ONLY. LAN accounts show up with a team prefix ("HAVOK SwizzY", "DVS Crusades", "orz Rura") that the linker's
exact-name matching can't see, so they stay separate players that never merge into the real pro. This lists them.

  [A] sheet pros NOT resolved by merge_from_linker/verify_linker -> live players that look like that pro
      (same name after dropping a leading team-prefix word, or name ends with / contains the pro's name)
  [B] sheet pros that ARE resolved -> OTHER live players that look like that pro (leftover prefixed duplicates)

For every candidate: placements, tournaments, and whether it shares a tournament with the pro's own player
(sharing one means two different people -- never merge those).

    python3 scripts/find_prefixed_duplicates.py
    python3 scripts/find_prefixed_duplicates.py --grep Crusades
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, PlayerAlias  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.services.player_identity import norm_id, skeleton  # noqa: E402
from scripts.merge_from_linker import DEFAULT_FILE, build_groups, load_rows  # noqa: E402

_TOMB = "[MERGED INTO"


def prefixless(name: str) -> str | None:
    """Skeleton of the name with its first space-separated word dropped (None if it has no space)."""
    parts = name.strip().split()
    return skeleton(" ".join(parts[1:])) if len(parts) >= 2 else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--grep", default="")
    args = ap.parse_args()

    groups = build_groups(load_rows(Path(args.file)))
    db = SessionLocal()
    try:
        players = [p for p in db.query(Player).all() if not p.gamertag.startswith(_TOMB)]
        by_id = {p.id: p for p in players}
        pcount = dict(db.query(PlacementResult.player_id, func.count(PlacementResult.id)).group_by(PlacementResult.player_id).all())
        tnames = {tid: (name, st) for tid, name, st in db.query(Tournament.id, Tournament.name, Tournament.start_time).all()}
        tsets: dict = defaultdict(set)
        for pid, tid in db.query(PlacementResult.player_id, PlacementResult.tournament_id).all():
            tsets[pid].add(tid)
        maps = {norm_id(m.osirion_account_id): m for m in db.query(OsirionPlayerMapping).all()}
        aliases = {a.alias_key: a for a in db.query(PlayerAlias).all()}
        sk_live = defaultdict(list)
        for p in players:
            sk_live[skeleton(p.gamertag)].append(p)
        mapped_name = defaultdict(set)
        for m in maps.values():
            if m.osirion_username and m.player_id in by_id:
                mapped_name[skeleton(m.osirion_username)].add(m.player_id)

        def resolve(g):
            targets = {}
            for i in g["epic_ids"]:
                m = maps.get(norm_id(i))
                if m is not None and m.player_id in by_id:
                    targets[m.player_id] = by_id[m.player_id]
            if not targets:
                for n in g["names"]:
                    a = aliases.get(skeleton(n))
                    if a is not None and a.player_id in by_id:
                        targets[a.player_id] = by_id[a.player_id]
                    for p in sk_live.get(skeleton(n), []):
                        targets[p.id] = p
                    for pid in mapped_name.get(skeleton(n), ()):
                        targets[pid] = by_id[pid]
            return list(targets.values())

        def candidates(g, exclude_ids):
            keys = {skeleton(g["pro"])} | {skeleton(n) for n in g["names"]}
            keys = {k for k in keys if len(k) >= 3}
            out = []
            for p in players:
                if p.id in exclude_ids:
                    continue
                full, pre = skeleton(p.gamertag), prefixless(p.gamertag)
                why = None
                if pre is not None and pre in keys:
                    why = "prefix + exact"
                elif any(full.endswith(k) and full != k for k in keys):
                    why = "name ends with"
                elif any(k in full and full != k and len(k) >= 4 for k in keys):
                    why = "name contains"
                if why:
                    out.append((p, why))
            return out

        def describe(p):
            ts = sorted((tnames[t] for t in tsets[p.id] if t in tnames), key=lambda x: (x[1] is None, x[1]))
            first = "; ".join(n for n, _ in ts[:2])
            return f"{p.gamertag!r} (id={str(p.id)[:8]}, placements={pcount.get(p.id, 0)}, {'active' if p.is_active else 'INACTIVE'}) in: {first}{' ...' if len(ts) > 2 else ''}"

        unresolved, resolved_dups = [], []
        for g in groups:
            label = f"[{'/'.join(g['player_ids']) or '?'}] {g['pro']}"
            if args.grep and args.grep.lower() not in label.lower() and not any(args.grep.lower() in n.lower() for n in g["names"]):
                continue
            targets = resolve(g)
            if not targets:
                unresolved.append((label, g, candidates(g, set())))
            elif len(targets) == 1:
                t = targets[0]
                c = candidates(g, {t.id})
                if c:
                    resolved_dups.append((label, g, t, c))

        print("=" * 100)
        print(f"[A] Sheet pros NOT in the database by ID/name -- possible prefixed accounts ({len(unresolved)} pros)\n")
        for label, g, cands in unresolved:
            print(f"{label}   sheet names: {', '.join(g['names']) or '(none)'}")
            if not cands:
                print("    (no look-alike player at all)")
            for p, why in cands:
                print(f"    ? {describe(p)}   [{why}]")
        print("\n" + "=" * 100)
        print(f"[B] RESOLVED pros that still have look-alike players ({len(resolved_dups)} pros)\n")
        for label, g, t, cands in resolved_dups:
            print(f"{label}  -> main: {describe(t)}")
            for p, why in cands:
                shared = bool(tsets[p.id] & tsets[t.id])
                print(f"    ? {describe(p)}   [{why}]" + ("   <-- SHARES a tournament with the main player: different person" if shared else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main()
