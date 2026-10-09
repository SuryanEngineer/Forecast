#!/usr/bin/env python3
"""
Merge each pro's accounts into ONE player, driven by the hand-verified spreadsheet
scripts/data/lan_main_linker.csv ("LAN to Main Account Fortnite Linker").

HOW IT WORKS (no pro-name matching, no fuzzy matching):
  1. EPIC ID   Each sheet row's permanent Epic account ID is looked up in
               OsirionPlayerMapping.osirion_account_id (already stored by every sync;
               nothing external is queried). The player it points to is the pro's
               SURVIVING player (the "target"). If a pro has several IDs (e.g. P130 Ark,
               two rows) and they map to different players, the one with the most
               placements survives and the others are merged into it.
  2. LAN NAMES Any other player whose name EXACTLY equals one of the sheet's LAN
               account names for that pro ("Account Name at EWC 2026", "... at Global
               Championship", plus any name quoted in Notes) is merged into the target.
               "Exactly" = ignoring [tags], case, accents, look-alike letters and
               punctuation.
  3. RENAME    The sheet's "Pro Name (auto)" becomes the target's gamertag, so the
               display name is the one WE list, whatever the account calls itself in game.
               (Future syncs still match the player by Epic account ID, so the name
               never flips back.)

If a pro's Epic ID isn't in the database (e.g. a pro from another region who only shows up
at LAN events) but players carrying the sheet's LAN account names exist, all of those are
combined into one (most placements survives, marked [name-only]) and renamed to the pro
name. Only a pro with neither an ID nor a LAN-name match is NOT FOUND. The pro name itself
is never used to find players.

SAFETY (reused from merge_fuzzy_duplicates.py): a player is never merged away if a real
(non-bot, non-House) user holds shares, has an order, got a dividend from it, or traded
it -- it is left untouched and flagged. Placements/dividends colliding with the target's
for the same tournament are skipped and reported. Merged-away rows are tombstoned
("[MERGED INTO ...]") and deactivated; an inactive target is reactivated. A player claimed
by two different pros is dropped from both and reported. If the pro name is already used
by another player, that player is merged into the target too (so the rename can happen); the
only exception is when it is itself another pro's surviving player, then the rename is skipped
and reported.

Usage:
    cd forecast-backend
    python3 scripts/merge_from_linker.py                   # dry run: no writes
    python3 scripts/merge_from_linker.py --confirm         # apply (no prompts)
    python3 scripts/merge_from_linker.py --only P001,P130  # restrict to some Player IDs
    python3 scripts/merge_from_linker.py --file other.xlsx # .csv or .xlsx (needs openpyxl)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, PlayerAlias  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402
from app.services.player_identity import norm_id, skeleton  # noqa: E402
from scripts.merge_fuzzy_duplicates import (  # noqa: E402
    _TOMBSTONE_PREFIX,
    _merge_player,
    _placement_count,
    _real_user_ids,
    _why_unsafe_to_merge_away,
)

DEFAULT_FILE = Path(__file__).parent / "data" / "lan_main_linker.csv"

_QUOTED = re.compile(r'["“]([^"”]+)["”]')


# --------------------------------------------------------------------------- sheet loading

def load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            sys.exit("Reading .xlsx needs openpyxl (pip install openpyxl) -- or pass the .csv instead.")
        ws = openpyxl.load_workbook(path, read_only=True).active
        raw = [["" if c is None else str(c) for c in row[:7]] for row in ws.iter_rows(values_only=True)]
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            raw = [row[:7] for row in csv.reader(f)]
    raw = [r for r in raw if any(x.strip() for x in r)]
    header = [h.strip().lower() for h in raw[0]]

    def col(prefix: str) -> int:
        for i, h in enumerate(header):
            if h.startswith(prefix):
                return i
        sys.exit(f"Spreadsheet is missing a column starting with {prefix!r}. Found: {raw[0]}")

    c_id, c_pid, c_pro = col("epic account id"), col("player id"), col("pro name")
    c_ewc, c_gc, c_notes = col("account name at ewc"), col("account name at global"), col("notes")
    rows = []
    for r in raw[1:]:
        r = r + [""] * (7 - len(r))
        rows.append({
            "epic_id": r[c_id].strip(), "player_id": r[c_pid].strip(), "pro": r[c_pro].strip(),
            "ewc": r[c_ewc].strip(), "gc": r[c_gc].strip(), "notes": r[c_notes].strip(),
        })
    return rows


def build_groups(rows: list[dict]) -> list[dict]:
    """One group per Player ID (rows sharing a Player ID are one person). Pro name is only the
    display name -- it is not used to group or match."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["player_id"] or ("id:" + norm_id(r["epic_id"]))].append(r)

    groups = []
    for members in grouped.values():
        names: list[str] = []
        for m in members:
            for n in (m["ewc"], m["gc"], *_QUOTED.findall(m["notes"])):
                if n and n not in names:
                    names.append(n)
        groups.append({
            "player_ids": sorted({m["player_id"] for m in members if m["player_id"]}),
            "pro": members[0]["pro"],
            "epic_ids": [m["epic_id"] for m in members if m["epic_id"]],
            "names": names,
            "notes": " | ".join(m["notes"] for m in members if m["notes"]),
        })
    groups.sort(key=lambda g: g["player_ids"][0] if g["player_ids"] else g["pro"])
    return groups


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Linker spreadsheet (.csv or .xlsx).")
    parser.add_argument("--confirm", action="store_true", help="Apply merges + renames. Without it, a dry run.")
    parser.add_argument("--exact-only", action="store_true", help=argparse.SUPPRESS)  # legacy no-op (always exact now)
    parser.add_argument("--only", default="", help="Comma-separated Player IDs (e.g. P011,P130) to restrict to.")
    args = parser.parse_args()

    rows = load_rows(args.file)
    groups = build_groups(rows)
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        groups = [g for g in groups if wanted & set(g["player_ids"])]
    print(f"Loaded {len(rows)} sheet row(s) -> {len(groups)} pro(s) from {args.file.name}.")

    db = SessionLocal()
    db.expire_on_commit = False  # keep loaded Players valid across the commits inside _merge_player
    try:
        real_user_ids = _real_user_ids(db)
        all_players = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).all()
        by_skeleton: dict[str, list[Player]] = defaultdict(list)
        by_exact_lower: dict[str, list[Player]] = defaultdict(list)
        for p in all_players:
            by_skeleton[skeleton(p.gamertag)].append(p)
            by_exact_lower[p.gamertag.strip().casefold()].append(p)
        live_by_id = {p.id: p for p in all_players}
        # Every account the sync has ever attached to a player remembers the name it played under
        # (OsirionPlayerMapping.osirion_username). After a pro is renamed to the sheet's pro name, THIS is
        # how their LAN account name still resolves to them on a re-run.
        by_mapped_name: dict[str, set] = defaultdict(set)
        for mp in db.query(OsirionPlayerMapping).all():
            if mp.osirion_username and mp.player_id in live_by_id:
                by_mapped_name[skeleton(mp.osirion_username)].add(mp.player_id)

        # ---- Epic ID -> player
        sheet_ids = {norm_id(i) for g in groups for i in g["epic_ids"]}
        id_to_player: dict[str, Player] = {}
        if sheet_ids:
            mappings = (
                db.query(OsirionPlayerMapping)
                .filter(func.replace(func.lower(OsirionPlayerMapping.osirion_account_id), "-", "").in_(sheet_ids))
                .all()
            )
            for m in mappings:
                player = db.get(Player, m.player_id)
                if player is not None and not player.gamertag.startswith(_TOMBSTONE_PREFIX):
                    id_to_player[norm_id(m.osirion_account_id)] = player
        total_ids = sum(len(g["epic_ids"]) for g in groups)
        hit_ids = sum(1 for g in groups for i in g["epic_ids"] if norm_id(i) in id_to_player)
        print(f"Epic-ID matches against OsirionPlayerMapping: {hit_ids}/{total_ids} sheet account(s).\n")

        # ---- pass 1: ID players (targets) and exact-LAN-name players (sources) per group
        for g in groups:
            id_players: dict = {}
            for i in g["epic_ids"]:
                p = id_to_player.get(norm_id(i))
                if p is not None:
                    id_players[p.id] = p
            name_players: dict = {}
            for n in g["names"]:
                for p in by_skeleton.get(skeleton(n), []):
                    name_players[p.id] = (p, clean_gamertag(n))
                for pid in by_mapped_name.get(skeleton(n), ()):
                    name_players.setdefault(pid, (live_by_id[pid], clean_gamertag(n)))
            g["id_players"] = id_players
            g["name_players"] = name_players

        # ---- a player claimed by two different pros is ambiguous: drop from both
        claims: dict = defaultdict(set)
        for gi, g in enumerate(groups):
            for pid in list(g["id_players"]) + list(g["name_players"]):
                claims[pid].add(gi)
        conflicts = []
        for pid, gis in claims.items():
            if len(gis) > 1:
                p = next((groups[gi]["id_players"].get(pid) or groups[gi]["name_players"][pid][0]) for gi in gis)
                conflicts.append((p.gamertag, ", ".join(f"{(groups[gi]['player_ids'] or ['?'])[0]} {groups[gi]['pro']}"
                                                         for gi in sorted(gis))))
                for gi in gis:
                    groups[gi]["id_players"].pop(pid, None)
                    groups[gi]["name_players"].pop(pid, None)

        # ---- pick target + sources
        for g in groups:
            basis = "epic-id"
            pool = list(g["id_players"].values())
            if not pool:
                # Epic ID not in the DB (e.g. a pro from another region who only appears at LAN events):
                # combine every player carrying one of the sheet's LAN account names under the pro name.
                pool = [p for p, _n in g["name_players"].values()]
                basis = "name-only"
            pool.sort(key=lambda p: (_placement_count(db, p.id), p.is_active), reverse=True)
            g["target"] = pool[0] if pool else None
            g["basis"] = basis
            sources = {}
            for p in g["id_players"].values():
                sources[p.id] = (p, "epic-id")
            for p, n in g["name_players"].values():
                sources.setdefault(p.id, (p, f"LAN name {n!r}"))
            if g["target"] is not None:
                sources.pop(g["target"].id, None)
            g["sources"] = list(sources.values())
        main_targets = {g["target"].id for g in groups if g["target"] is not None}

        # ---- report / apply
        stats = defaultdict(int)
        not_found, skipped_unsafe, rename_blocked = [], [], []
        for g in groups:
            label = f"[{'/'.join(g['player_ids']) or '?'}] {g['pro']}"
            target = g["target"]
            if target is None:
                stats["not found"] += 1
                not_found.append(label)
                print(f"{label}: NOT FOUND (Epic ID(s) not in the database; no unique exact LAN-name match).")
                continue
            pro_name = g["pro"].strip()
            # A player already carrying exactly the pro name (case-insensitive) is the same person
            # (the sheet's Epic ID / LAN account is the verified link; a stray row of the same name is
            # that pro's own duplicate) -- merge it in so the rename can happen.
            have = {p.id for p, _ in g["sources"]}
            for p in by_exact_lower.get(pro_name.casefold(), []):
                if p.id != target.id and p.id not in have:
                    g["sources"].append((p, f"already named {pro_name!r}"))
            # a different pro's target can never be this pro's source
            g["sources"] = [(p, r) for p, r in g["sources"] if p.id not in main_targets]

            rename = bool(pro_name) and target.gamertag != pro_name
            source_ids = {p.id for p, _ in g["sources"]}
            blockers = [p for p in by_exact_lower.get(pro_name.casefold(), [])
                        if p.id != target.id and p.id not in source_ids]
            if rename and blockers:
                rename = False
                rename_blocked.append(f"{label}: name {pro_name!r} already used by unrelated player(s) "
                                      + ", ".join(f"{p.gamertag!r} (placements={_placement_count(db, p.id)})" for p in blockers))

            if not g["sources"] and not rename:
                stats["nothing to do"] += 1
                continue

            print("=" * 100)
            print(f"{label}   sheet LAN name(s): {', '.join(g['names']) or '(none)'}")
            if g["notes"]:
                print(f"    note: {g['notes']}")
            print(f"    TARGET: id={target.id}  {target.gamertag!r}  placements={_placement_count(db, target.id)}  "
                  f"{'active' if target.is_active else 'INACTIVE'}   [{g['basis']}]")
            for p, why in g["sources"]:
                print(f"    MERGE IN: id={p.id}  {p.gamertag!r}  placements={_placement_count(db, p.id)}  "
                      f"{'active' if p.is_active else 'INACTIVE'}   [{why}]")
            if rename:
                print(f"    RENAME: {target.gamertag!r} -> {pro_name!r}")

            if not args.confirm:
                stats["would merge"] += len(g["sources"])
                stats["would rename"] += int(rename)
                continue

            for source, _why in g["sources"]:
                if source.id == target.id or source.gamertag.startswith(_TOMBSTONE_PREFIX):
                    continue
                reason = _why_unsafe_to_merge_away(db, source.id, real_user_ids)
                if reason is not None:
                    print(f"  SKIPPED -- {source.gamertag!r} {reason}. Left completely untouched.")
                    skipped_unsafe.append(f"{label}: {source.gamertag!r} {reason}")
                    stats["skipped unsafe"] += 1
                    continue
                s = _merge_player(db, source, target)
                stats["merged"] += 1
                note = " (target was inactive -- reactivated)" if s["target_reactivated"] else ""
                print(f"  Merged {source.gamertag!r} -> {target.gamertag!r}{note}: {s['mappings_moved']} mapping(s), "
                      f"{s['placements_moved']} placement(s) moved ({s['placements_conflicted']} skipped as duplicate "
                      f"tournament), {s['dividends_moved']} dividend payout(s) moved "
                      f"({s['dividends_conflicted']} skipped as duplicate tournament).")

            if rename:
                # re-check right before writing: a merged source may have held a clashing name (now tombstoned)
                clash = (
                    db.query(Player)
                    .filter(func.lower(Player.gamertag) == pro_name.casefold(), Player.id != target.id)
                    .first()
                )
                if clash is not None:
                    print(f"  RENAME SKIPPED -- {clash.gamertag!r} still uses that name.")
                    rename_blocked.append(f"{label}: {pro_name!r} still used by {clash.gamertag!r}")
                else:
                    old = target.gamertag
                    target.gamertag = pro_name
                    db.commit()
                    stats["renamed"] += 1
                    print(f"  Renamed {old!r} -> {pro_name!r}")

        # ---- register every sheet LAN account name as an alias of its pro, so a LAN account the
        # sync has never seen (new account id, same name) is attached to the right player instead of
        # becoming a duplicate stock. Also the safety net for events after this one.
        existing_aliases = {a.alias_key: a for a in db.query(PlayerAlias).all()}
        alias_new, alias_conflicts, verify_new = 0, [], 0
        for g in groups:
            target = g["target"]
            if target is None:
                continue
            # Every pro listed in the sheet (whose name we normalized) gets the "Verified" badge.
            if not target.is_verified:
                verify_new += 1
                if args.confirm:
                    target.is_verified = True
            for n in g["names"]:
                key = skeleton(n)
                have = existing_aliases.get(key)
                if have is not None:
                    if have.player_id != target.id:
                        alias_conflicts.append(f"[{'/'.join(g['player_ids'])}] {g['pro']}: {clean_gamertag(n)!r} already an alias of another player")
                    continue
                if args.confirm:
                    row = PlayerAlias(alias_key=key, alias_name=clean_gamertag(n)[:200], player_id=target.id, source="linker")
                    db.add(row)
                    existing_aliases[key] = row
                alias_new += 1
        if args.confirm:
            db.commit()
        stats["aliases registered" if args.confirm else "aliases to register"] += alias_new
        stats["marked verified" if args.confirm else "to mark verified"] += verify_new

        print("\n" + "=" * 100)
        print("SUMMARY")
        if alias_conflicts:
            print("  Alias conflicts (left as-is):")
            for line in alias_conflicts:
                print(f"    {line}")
        for k in ("merged", "renamed", "would merge", "would rename", "aliases registered", "aliases to register", "marked verified", "to mark verified", "skipped unsafe", "nothing to do", "not found"):
            if stats.get(k):
                print(f"  {k}: {stats[k]}")
        if conflicts:
            print(f"  {len(conflicts)} player(s) matched TWO different pros and were left alone:")
            for gamertag, who in conflicts:
                print(f"    {gamertag!r} claimed by {who}")
        if rename_blocked:
            print("  Rename blocked (name already used by another, unlinked player):")
            for line in rename_blocked:
                print(f"    {line}")
        if not_found:
            print(f"  Not found ({len(not_found)}): " + ", ".join(not_found))
        if skipped_unsafe:
            print("  Left untouched because a real user holds/ordered/traded them:")
            for line in skipped_unsafe:
                print(f"    {line}")
        if not args.confirm:
            print("\nDry run only -- nothing changed. Re-run with --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
