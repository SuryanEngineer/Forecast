#!/usr/bin/env python3
"""
Merge LAN accounts that carry a team prefix ("HAVOK SwizzY", "DVS Crusades", "orz Rura", "BIG Malibuca 7") into the
pro they belong to, so leaderboards show the NORMALIZED pro name and the pro's stock gets the LAN placements.

merge_from_linker.py only matches LAN names exactly (tags in [brackets] ignored), so these prefixed accounts stayed
separate players. This script finds them with strict rules -- a candidate is merged only if ALL hold:
  * its name, with a leading team-prefix word dropped and trailing digits ("7", "10!", "281") removed, equals the pro's
    name or one of the pro's sheet LAN names (see player_identity.lan_core_keys) -- never a fuzzy "contains";
  * it has placed ONLY in on-site (LAN) tournaments -- a prefixed account is a LAN account, never a pubs/qualifier one;
  * it never shared a tournament with the pro's own player (or with another account being merged in): two entries in
    one lobby are two different people;
  * its Epic account id is not listed in the sheet under a different pro (the ID always wins over the name);
  * it isn't claimed by two different pros, isn't another pro's own player, and no real user holds/ordered/traded it.

A pro with NO player yet in the database (the "not found" ones) gets the best candidate as their player, renamed to the
sheet's Pro Name and marked verified. Every merged account name is registered as an alias, and its Epic account id now
points at the pro, so future LAN syncs link automatically.

Dry run by default.

    python3 scripts/merge_prefixed_accounts.py                 # plan only
    python3 scripts/merge_prefixed_accounts.py --confirm       # apply
    python3 scripts/merge_prefixed_accounts.py --only P047,P133
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
from app.services.osirion_service import clean_gamertag  # noqa: E402
from app.services.player_identity import lan_core_keys, leet_fold, norm_id, skeleton  # noqa: E402
from scripts.merge_fuzzy_duplicates import (  # noqa: E402
    _TOMBSTONE_PREFIX,
    _merge_player,
    _real_user_ids,
    _why_unsafe_to_merge_away,
)
from scripts.merge_from_linker import DEFAULT_FILE, build_groups, load_rows  # noqa: E402

LAN_REGION = "ONSITE"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--only", default="", help="Comma-separated Player IDs (e.g. P047,P133).")
    args = ap.parse_args()

    groups = build_groups(load_rows(Path(args.file)))
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        groups = [g for g in groups if wanted & set(g["player_ids"])]

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        players = [p for p in db.query(Player).all() if not p.gamertag.startswith(_TOMBSTONE_PREFIX)]
        by_id = {p.id: p for p in players}
        pcount = dict(db.query(PlacementResult.player_id, func.count(PlacementResult.id)).group_by(PlacementResult.player_id).all())
        region_of = {tid: reg for tid, reg in db.query(Tournament.id, Tournament.region).all()}
        tsets: dict = defaultdict(set)
        for pid, tid in db.query(PlacementResult.player_id, PlacementResult.tournament_id).all():
            tsets[pid].add(tid)

        def lan_only(p: Player) -> bool:
            ts = tsets.get(p.id)
            return bool(ts) and all(str(region_of.get(t) or "").upper() == LAN_REGION for t in ts)

        maps = {norm_id(m.osirion_account_id): m for m in db.query(OsirionPlayerMapping).all()}
        aliases = {a.alias_key: a for a in db.query(PlayerAlias).all()}
        ids_by_player: dict = defaultdict(list)
        for m in maps.values():
            ids_by_player[m.player_id].append(m.osirion_account_id)
        sk_live: dict = defaultdict(list)
        for p in players:
            sk_live[skeleton(p.gamertag)].append(p)
        mapped_name: dict = defaultdict(set)
        for m in maps.values():
            if m.osirion_username and m.player_id in by_id:
                mapped_name[skeleton(m.osirion_username)].add(m.player_id)

        # ---- each pro's own (main) player(s), resolved exactly like verify_linker does
        for g in groups:
            t: dict = {}
            for i in g["epic_ids"]:
                m = maps.get(norm_id(i))
                if m is not None and m.player_id in by_id:
                    t[m.player_id] = by_id[m.player_id]
            if not t:
                for n in g["names"]:
                    a = aliases.get(skeleton(n))
                    if a is not None and a.player_id in by_id:
                        t[a.player_id] = by_id[a.player_id]
                    for p in sk_live.get(skeleton(n), []):
                        t[p.id] = p
                    for pid in mapped_name.get(skeleton(n), ()):
                        t[pid] = by_id[pid]
            g["main"] = t
            keys = {skeleton(g["pro"])}
            for n in g["names"]:
                keys |= {skeleton(n)} | lan_core_keys(n)
            keys |= lan_core_keys(g["pro"])
            g["keys"] = {k for k in keys if len(k) >= 3}
        all_mains = {pid for g in groups for pid in g["main"]}
        sheet_id_owner = {norm_id(i): gi for gi, g in enumerate(groups) for i in g["epic_ids"]}

        # ---- candidates per pro
        claims: dict = defaultdict(set)
        # Players that match SOME pro exactly never use the digit/letter fallback (Cringe vs Cr1nge stay apart).
        exact_any = {p.id for p in players if any(lan_core_keys(p.gamertag) & g["keys"] for g in groups)}
        for g in groups:
            g["leet_keys"] = {leet_fold(k) for k in g["keys"]}
        for gi, g in enumerate(groups):
            g["cands"] = {}
            for p in players:
                if p.id in all_mains or p.id in g["main"] or not lan_only(p):
                    continue
                pk = lan_core_keys(p.gamertag)
                hit = bool(pk & g["keys"])
                if not hit and p.id not in exact_any:
                    hit = bool({leet_fold(k) for k in pk} & g["leet_keys"])
                if hit:
                    owners = {sheet_id_owner[norm_id(i)] for i in ids_by_player.get(p.id, []) if norm_id(i) in sheet_id_owner}
                    if owners - {gi}:
                        continue  # this account's Epic ID is listed under a DIFFERENT pro -- the ID wins over the name
                    g["cands"][p.id] = p
                    claims[p.id].add(gi)
        conflicted = {pid for pid, gis in claims.items() if len(gis) > 1}
        conflict_lines = []
        for pid in conflicted:
            p = by_id[pid]
            conflict_lines.append(f"{p.gamertag!r} matches several pros: " + ", ".join(f"{groups[gi]['pro']}" for gi in sorted(claims[pid])))
            for gi in claims[pid]:
                groups[gi]["cands"].pop(pid, None)

        real_user_ids = _real_user_ids(db)
        plan, notes = [], []
        for g in groups:
            label = f"[{'/'.join(g['player_ids']) or '?'}] {g['pro']}"
            if not g["cands"]:
                continue
            if len(g["main"]) > 1:
                notes.append(f"{label}: resolves to several players ({', '.join(repr(p.gamertag) for p in g['main'].values())}) -- skipped")
                continue
            cands = sorted(g["cands"].values(), key=lambda p: (pcount.get(p.id, 0), p.is_active), reverse=True)
            accepted: list[Player] = []
            if g["main"]:
                target = next(iter(g["main"].values()))
                accepted_sets = [tsets.get(target.id, set())]
                basis = "existing player"
            else:
                target = cands[0]
                accepted_sets = [tsets.get(target.id, set())]
                cands = cands[1:]
                basis = "no player yet -- best candidate becomes the pro"
            for p in cands:
                if any(tsets.get(p.id, set()) & s for s in accepted_sets):
                    notes.append(f"{label}: {p.gamertag!r} shares a tournament with the pro/other merged accounts -- different person, left alone")
                    continue
                accepted.append(p)
                accepted_sets.append(tsets.get(p.id, set()))
            plan.append((label, g, target, accepted, basis))

        for label, g, target, accepted, basis in plan:
            rename = target.gamertag != g["pro"].strip()
            print("=" * 100)
            print(f"{label}   [{basis}]")
            print(f"    TARGET: {target.gamertag!r}  (placements={pcount.get(target.id, 0)})" + (f"  -> RENAME to {g['pro']!r}" if rename else ""))
            for p in accepted:
                ids = ", ".join(i[:8] for i in ids_by_player.get(p.id, [])) or "none"
                print(f"    MERGE IN: {p.gamertag!r}  (placements={pcount.get(p.id, 0)}, Epic id(s): {ids})")
        print("\n" + "=" * 100)
        print(f"{len(plan)} pro(s) with prefixed accounts; {sum(len(a) for *_, a, _b in plan)} account(s) to merge in.")
        for line in conflict_lines:
            print(f"  conflict: {line}")
        for line in notes:
            print(f"  note: {line}")

        if not args.confirm:
            print("\nDry run only -- nothing changed. Re-run with --confirm to apply.")
            return

        merged = skipped = renamed = 0
        for label, g, target, accepted, _basis in plan:
            for p in accepted:
                reason = _why_unsafe_to_merge_away(db, p.id, real_user_ids)
                if reason is not None:
                    print(f"  SKIPPED -- {p.gamertag!r} {reason}. Left untouched.")
                    skipped += 1
                    continue
                s = _merge_player(db, p, target)
                merged += 1
                print(f"  Merged {p.gamertag!r} -> {target.gamertag!r}: {s['mappings_moved']} mapping(s), "
                      f"{s['placements_moved']} placement(s) moved ({s['placements_conflicted']} skipped as duplicate)")
                key = skeleton(p.gamertag)
                if key not in aliases:
                    row = PlayerAlias(alias_key=key, alias_name=clean_gamertag(p.gamertag)[:200], player_id=target.id, source="linker-prefix")
                    db.add(row)
                    aliases[key] = row
            pro_name = g["pro"].strip()
            if pro_name and target.gamertag != pro_name:
                clash = db.query(Player).filter(func.lower(Player.gamertag) == pro_name.casefold(), Player.id != target.id).first()
                if clash is not None:
                    print(f"  RENAME SKIPPED -- {clash.gamertag!r} already uses {pro_name!r}")
                else:
                    target.gamertag = pro_name
                    renamed += 1
                    print(f"  Renamed to {pro_name!r}")
            target.is_verified = True
            for n in g["names"]:
                key = skeleton(n)
                if key not in aliases:
                    row = PlayerAlias(alias_key=key, alias_name=clean_gamertag(n)[:200], player_id=target.id, source="linker")
                    db.add(row)
                    aliases[key] = row
            db.commit()
        print(f"\nDone: merged {merged}, renamed {renamed}, skipped (real holders) {skipped}.")
        print("Next: python3 scripts/verify_linker.py   and   python3 scripts/find_prefixed_duplicates.py")
    finally:
        db.close()


if __name__ == "__main__":
    main()
