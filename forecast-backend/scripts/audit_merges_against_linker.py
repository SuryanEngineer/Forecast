#!/usr/bin/env python3
"""
READ-ONLY audit: did every merge we already performed land on the right person,
judged against the verified linker spreadsheet (scripts/data/lan_main_linker.csv)?

Nothing is written to the database. For every tombstoned player (gamertag starting
"[MERGED INTO ...]") it works out:
  - which pro in the sheet the MERGED-AWAY row belongs to, and
  - which pro in the sheet the player that ABSORBED it belongs to,
and compares them. It also lists every ACTIVE bracket-tagged player that can't be
tied to any pro in the sheet at all (you said every tagged player should be in the
sheet, so each of those is either a sheet gap or a stray row).

How a player is tied to a sheet pro (strongest first):
  id     -- one of its Osirion account ids equals the sheet's permanent Epic id
  exact  -- its name (tags stripped, case/accents/look-alikes normalised) equals a
            sheet account name for exactly one pro
  fuzzy  -- clearly closest to one pro's names (>= 0.78 similarity with a margin
            over the runner-up) or contains that pro's name. WEAK evidence.

Verdicts per merge:
  OK          both sides resolve to the same pro by id/exact
  OK (fuzzy)  same pro, but at least one side is only fuzzy-resolved
  WRONG       both sides resolve to DIFFERENT pros by id/exact -- a bad merge
  SUSPECT     different pros but at least one side is fuzzy-only -- look by hand
  UNVERIFIED  only one side could be tied to a pro
  UNKNOWN     neither side could be tied to any pro

The merged-away row's original name comes from the tombstone itself; the player that
currently holds its data is found via the Osirion mapping whose saved original
username equals that name (so chains of merges resolve to the final holder), falling
back to the target named in the tombstone.

Writes a CSV (default merge_audit.csv in the current directory) with every merge and
verdict, so you can open it in Excel.

Usage:
    cd forecast-backend
    python3 scripts/audit_merges_against_linker.py
    python3 scripts/audit_merges_against_linker.py --out C:\\temp\\audit.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from scripts.merge_from_linker import (  # noqa: E402
    DEFAULT_FILE,
    build_groups,
    is_lan_tagged,
    load_rows,
    norm_id,
    skeleton,
)

_PREFIX = "[MERGED INTO "
_FUZZY_MIN = 0.78
_FUZZY_MARGIN = 0.05


def parse_tombstone(gamertag: str) -> tuple[str, str] | None:
    """'[MERGED INTO <target>] <source>' -> (target, source). The target itself may contain
    brackets (e.g. '[FNCSGC26] x'), so find the matching close bracket by depth."""
    if not gamertag.startswith(_PREFIX):
        return None
    rest = gamertag[len(_PREFIX):]
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "[":
            depth += 1
        elif ch == "]":
            if depth == 0:
                return rest[:i], rest[i + 1:].strip()
            depth -= 1
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--out", type=Path, default=Path("merge_audit.csv"))
    args = parser.parse_args()

    groups = build_groups(load_rows(args.file))
    labels = [f"{'/'.join(g['player_ids']) or '?'} {g['pro']}" for g in groups]
    id_map: dict[str, int] = {}
    exact_map: dict[str, set] = defaultdict(set)
    group_skels: list[list[str]] = []
    pro_skels: list[str] = []
    for idx, g in enumerate(groups):
        for eid in g["epic_ids"]:
            id_map[norm_id(eid)] = idx
        sks = [skeleton(n) for n in g["names"]]
        group_skels.append([s for s in sks if s and not s.startswith("raw:")])
        for s in sks:
            exact_map[s].add(idx)
        pk = skeleton(g["pro"])
        pro_skels.append(pk if len(pk) >= 4 else "")

    def resolve(name: str, epic_ids: list[str]) -> tuple[int | None, str]:
        hits = {id_map[norm_id(e)] for e in epic_ids if norm_id(e) in id_map}
        if len(hits) == 1:
            return next(iter(hits)), "id"
        sk = skeleton(name)
        owners = exact_map.get(sk, set())
        if len(owners) == 1:
            return next(iter(owners)), "exact"
        if len(owners) > 1 or not sk or sk.startswith("raw:"):
            return None, "ambiguous"
        scored = []
        for idx in range(len(groups)):
            ratio = max((SequenceMatcher(None, sk, s).ratio() for s in group_skels[idx]), default=0.0)
            if pro_skels[idx] and pro_skels[idx] in sk:
                ratio = max(ratio, 0.95)
            scored.append((ratio, idx))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= _FUZZY_MIN and (len(scored) < 2 or scored[0][0] - scored[1][0] >= _FUZZY_MARGIN):
            return scored[0][1], "fuzzy"
        return None, "none"

    db = SessionLocal()
    try:
        all_players = db.query(Player).all()
        by_id = {p.id: p for p in all_players}
        by_name: dict[str, Player] = {p.gamertag: p for p in all_players}
        mappings = db.query(OsirionPlayerMapping).all()
        epic_by_player: dict = defaultdict(list)
        mapping_by_username: dict[str, list] = defaultdict(list)
        for m in mappings:
            epic_by_player[m.player_id].append(m.osirion_account_id)
            if m.osirion_username:
                mapping_by_username[m.osirion_username].append(m)

        tombstones = [(p, parse_tombstone(p.gamertag)) for p in all_players if p.gamertag.startswith(_PREFIX)]
        print(f"{len(groups)} pro(s) in the sheet; {len(tombstones)} merged-away player(s) in the database.\n")

        records = []
        absorbed_by_owner: dict = defaultdict(set)
        for t, parsed in tombstones:
            if parsed is None:
                records.append(dict(verdict="UNKNOWN", source_id=t.id, source_name=t.gamertag, owner_id="",
                                    owner_name="", source_pro="", owner_pro="", detail="could not parse tombstone"))
                continue
            target_name, source_name = parsed
            # current holder: the mapping that remembers this source's original username
            owner = None
            src_epics: list[str] = []
            for m in mapping_by_username.get(source_name, []):
                src_epics.append(m.osirion_account_id)
                holder = by_id.get(m.player_id)
                if holder is not None and not holder.gamertag.startswith(_PREFIX):
                    owner = holder
            hops = 0
            if owner is None:
                cur = by_name.get(target_name)
                while cur is not None and cur.gamertag.startswith(_PREFIX) and hops < 6:
                    nxt = parse_tombstone(cur.gamertag)
                    cur = by_name.get(nxt[0]) if nxt else None
                    hops += 1
                owner = cur if cur is not None and not cur.gamertag.startswith(_PREFIX) else None
            if owner is None:
                records.append(dict(verdict="UNKNOWN", source_id=t.id, source_name=source_name, owner_id="",
                                    owner_name=target_name, source_pro="", owner_pro="",
                                    detail="could not find the player that now holds this row's data"))
                continue

            gs, ms = resolve(source_name, src_epics)
            go, mo = resolve(owner.gamertag, epic_by_player.get(owner.id, []))
            strong = {"id", "exact"}
            if gs is not None and go is not None:
                if gs == go:
                    verdict = "OK" if (ms in strong and mo in strong) else "OK (fuzzy)"
                else:
                    verdict = "WRONG" if (ms in strong and mo in strong) else "SUSPECT"
            elif gs is None and go is None:
                verdict = "UNKNOWN"
            else:
                verdict = "UNVERIFIED"
            if gs is not None:
                absorbed_by_owner[owner.id].add((gs, ms))
            records.append(dict(
                verdict=verdict, source_id=t.id, source_name=source_name, owner_id=owner.id, owner_name=owner.gamertag,
                source_pro=f"{labels[gs]} ({ms})" if gs is not None else f"none ({ms})",
                owner_pro=f"{labels[go]} ({mo})" if go is not None else f"none ({mo})",
                detail="",
            ))

        # an owner that absorbed rows resolved to MORE THAN ONE pro is a red flag on its own
        for owner_id, absorbed in absorbed_by_owner.items():
            pros = {g for g, _ in absorbed}
            if len(pros) > 1:
                for r in records:
                    if r["owner_id"] == owner_id and r["verdict"].startswith("OK"):
                        r["verdict"] = "SUSPECT"
                        r["detail"] = "owner absorbed rows from several different pros"

        # active tagged players that map to no pro
        strays = []
        for p in all_players:
            if p.is_active and is_lan_tagged(p) and not p.gamertag.startswith(_PREFIX):
                g, method = resolve(p.gamertag, epic_by_player.get(p.id, []))
                if g is None:
                    strays.append(p)

        order = ["WRONG", "SUSPECT", "UNVERIFIED", "UNKNOWN", "OK (fuzzy)", "OK"]
        counts = defaultdict(int)
        for r in records:
            counts[r["verdict"]] += 1
        print("MERGE VERDICTS")
        for v in order:
            print(f"  {v}: {counts.get(v, 0)}")
        for v in ("WRONG", "SUSPECT", "UNVERIFIED", "UNKNOWN"):
            subset = [r for r in records if r["verdict"] == v]
            if not subset:
                continue
            print(f"\n--- {v} ({len(subset)}) ---")
            for r in subset:
                print(f"  {r['source_name']!r}  [{r['source_pro']}]  ->  {r['owner_name']!r}  [{r['owner_pro']}]"
                      + (f"   {r['detail']}" if r["detail"] else ""))
                print(f"      source id={r['source_id']}  owner id={r['owner_id']}")

        print(f"\n--- ACTIVE TAGGED PLAYERS NOT TIED TO ANY PRO IN THE SHEET ({len(strays)}) ---")
        print("  (you said every tagged player should be in the sheet: each of these is a sheet gap or a stray row)")
        for p in strays:
            print(f"  id={p.id}  {p.gamertag!r}")

        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["verdict", "source_name", "source_pro_in_sheet", "owner_name", "owner_pro_in_sheet", "source_id", "owner_id", "detail"])
            for v in order:
                for r in records:
                    if r["verdict"] == v:
                        w.writerow([v, r["source_name"], r["source_pro"], r["owner_name"], r["owner_pro"],
                                    r["source_id"], r["owner_id"], r["detail"]])
            for p in strays:
                w.writerow(["NOT IN SHEET", p.gamertag, "", "", "", p.id, "", "active tagged player with no matching pro"])
        print(f"\nFull results written to {args.out.resolve()}")
        print("Read-only audit -- nothing in the database was changed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
