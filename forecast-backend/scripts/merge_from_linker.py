#!/usr/bin/env python3
"""
Merge LAN/duplicate accounts into each pro's MAIN account, driven by the
hand-verified spreadsheet scripts/data/lan_main_linker.csv (converted from
"LAN to Main Account Fortnite Linker.xlsx").

Why this exists: every earlier merge script had to GUESS which rows are the same
person from gamertag spelling and/or tournament overlap. The spreadsheet replaces
guessing with verified ground truth: one row per (pro, Epic account), with the
account's permanent Epic ID and the name it carried at EWC 2026 / the Global
Championship. A pro who has two main accounts shows up on two rows sharing a
Player ID (e.g. P130 "Ark" -- main "dignitas ark!" plus "dig ark2x", the account
that won the NA West Last Chance Finals); all of a Player ID's rows are treated as
ONE person and merged together.

HOW A ROW IS RESOLVED TO DATABASE PLAYERS (strongest evidence first):
  1. EPIC ID  -- the sheet's permanent Epic ID, compared (case/dash-insensitive)
                 against OsirionPlayerMapping.osirion_account_id. This is an exact
                 identity match, no spelling involved.
  2. EXACT NAME -- the sheet's EWC / Global Championship account names (and any
                 name quoted in the Notes column), compared after removing bracket
                 tags and normalizing case, accents and look-alike characters
                 (Cyrillic "o" vs Latin "o", "ÿ" vs "y", decorative "!" etc.).
Every database player found by either method is "verified" -- it is the same
person as the pro. The MAIN (target) is the verified player that is not a
bracket-tagged LAN row, preferring the most placements; every other verified
player is merged into it.

OPTIONAL (UNVERIFIED) candidates: active players with at most 2 placements (typically
LAN-only accounts) that did NOT match by ID or exact name but whose name looks like this pro's (fuzzy similarity
to the sheet names, or containing the pro's name). These are only ever merged if
you explicitly pick them by number at the prompt -- never automatically.

SAFETY (reused from merge_fuzzy_duplicates.py, not re-implemented): a player is
never merged away if a real (non-bot, non-House) user holds shares, has an order,
received a dividend from it, or traded it -- it is left untouched and flagged.
Placements/dividends that would collide with the target's own for the same
tournament are skipped and reported. The merged-away row is tombstoned
("[MERGED INTO ...]") and deactivated; an inactive target is reactivated. A
player claimed by TWO different pros (name coincidence) is dropped from both and
reported rather than merged anywhere. A player that is itself the main account
of a different pro is never used as another pro's source.

Pros with no main account in the database (only a LAN row exists, or nobody
matched at all -- e.g. a region this app never ingested) are reported, not
merged: there is nothing to merge INTO.

Usage:
    cd forecast-backend
    python3 scripts/merge_from_linker.py                  # dry run: shows every
                                                            pro's resolution, no writes
    python3 scripts/merge_from_linker.py --confirm        # interactive, one prompt
                                                            per pro that has something
                                                            to merge
    python3 scripts/merge_from_linker.py --only P011,P130 # restrict to some Player IDs
    python3 scripts/merge_from_linker.py --file other.xlsx  # .csv or .xlsx (xlsx
                                                            needs `pip install openpyxl`)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402
from scripts.merge_fuzzy_duplicates import (  # noqa: E402
    _TOMBSTONE_PREFIX,
    _merge_player,
    _placement_count,
    _real_user_ids,
    _why_unsafe_to_merge_away,
)

DEFAULT_FILE = Path(__file__).parent / "data" / "lan_main_linker.csv"
_FUZZY_OPTIONAL_THRESHOLD = 0.72
_MAX_OPTIONALS = 8

# Look-alike characters used in Fortnite names (Cyrillic/Greek/etc. -> Latin).
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s",
    "ј": "j", "һ": "h", "ԁ": "d", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "ӏ": "l",
    "ν": "v", "ο": "o", "ρ": "p", "α": "a", "ι": "i", "τ": "t", "κ": "k", "ε": "e", "υ": "u",
    "β": "b", "ⅰ": "i", "ɑ": "a", "ı": "i", "ɡ": "g", "ø": "o", "đ": "d", "ł": "l",
})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_QUOTED = re.compile(r'["“]([^"”]+)["”]')


def skeleton(name: str) -> str:
    """Comparison key: tags stripped, accents removed, look-alikes folded, case and every
    non-alphanumeric dropped. Names with no Latin/digit content at all (e.g. Japanese)
    fall back to the raw casefolded text so they still compare."""
    cleaned = clean_gamertag(name)
    decomposed = unicodedata.normalize("NFKD", cleaned)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    # Keep letters/digits of ANY script (so a name like "QTD ふーくん" stays distinct from a bare "QTD"),
    # but drop whitespace/punctuation and the decorative "ǃ" (U+01C3, a letter-lookalike for "!").
    key = "".join(ch for ch in stripped.translate(_HOMOGLYPHS) if ch.isalnum() and ch != "ǃ")
    return key or ("raw:" + cleaned.casefold().strip())


def norm_id(value: str) -> str:
    return value.strip().lower().replace("-", "")


def is_lan_tagged(p: Player) -> bool:
    return p.gamertag.startswith("[")


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
    """One group per real person: rows sharing a Player ID (or the same pro name) are merged."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    first_by_pro: dict[str, str] = {}
    for r in rows:
        key = r["player_id"] or ("pro:" + r["pro"].lower())
        find(key)
        pro_key = r["pro"].strip().lower()
        if pro_key:
            if pro_key in first_by_pro:
                union(key, first_by_pro[pro_key])
            else:
                first_by_pro[pro_key] = key

    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[find(r["player_id"] or ("pro:" + r["pro"].lower()))].append(r)

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


# --------------------------------------------------------------------------- resolution

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Linker spreadsheet (.csv or .xlsx).")
    parser.add_argument("--confirm", action="store_true",
                        help="Interactively confirm and perform merges. Without it, a dry run: no prompts, no writes.")
    parser.add_argument("--auto-optionals", type=float, default=None, metavar="MIN_SIM",
                        help="With --confirm: skip the prompts. Merge each pro's verified sources PLUS optional candidates "
                             "whose similarity is >= MIN_SIM (e.g. 0.85) and that are a candidate for exactly ONE pro "
                             "(a look-alike offered to two different pros is never auto-merged). Dry run marks them [auto].")
    parser.add_argument("--exact-only", action="store_true",
                        help="Trust only the sheet: merge accounts that match a sheet Epic ID or an exact sheet name "
                             "(EWC/Global Championship names). No fuzzy look-alike suggestions, no prompts with --confirm.")
    parser.add_argument("--only", default="", help="Comma-separated Player IDs (e.g. P011,P130) to restrict to.")
    args = parser.parse_args()
    if args.exact_only:
        args.auto_optionals = 2.0  # prompt-free; no optional can reach similarity 2.0 (and none are generated)

    rows = load_rows(args.file)
    groups = build_groups(rows)
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        groups = [g for g in groups if wanted & set(g["player_ids"])]
    print(f"Loaded {len(rows)} sheet row(s) -> {len(groups)} pro(s) from {args.file.name}.")

    db = SessionLocal()
    # Keeps already-loaded Player objects valid across commits (see merge_qualified_duplicates.py).
    db.expire_on_commit = False
    try:
        real_user_ids = _real_user_ids(db)
        all_players = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).all()
        by_skeleton: dict[str, list[Player]] = defaultdict(list)
        for p in all_players:
            by_skeleton[skeleton(p.gamertag)].append(p)

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
        print(f"Epic-ID matches against OsirionPlayerMapping: {hit_ids}/{total_ids} sheet account(s).")
        if total_ids and hit_ids == 0:
            print("  (None matched -- Osirion's LAN account ids evidently differ from these permanent Epic ids, "
                  "so everything below resolves by exact name instead.)")
        print()

        # ---- pass 1: verified players per group (ID + exact name)
        for g in groups:
            verified: dict = {}  # player.id -> [Player, set(reasons)]
            for i in g["epic_ids"]:
                p = id_to_player.get(norm_id(i))
                if p is not None:
                    verified.setdefault(p.id, [p, set()])[1].add("epic-id")
            for n in g["names"]:
                for p in by_skeleton.get(skeleton(n), []):
                    verified.setdefault(p.id, [p, set()])[1].add(f"exact name {clean_gamertag(n)!r}")
            g["verified"] = verified

        # ---- players claimed by more than one pro are ambiguous: drop from all, report
        claims: dict = defaultdict(list)
        for g in groups:
            for pid in g["verified"]:
                claims[pid].append(g)
        conflicts = []
        for pid, claimants in claims.items():
            if len(claimants) > 1:
                who = ", ".join(f"{c['player_ids'][0] if c['player_ids'] else '?'} {c['pro']}" for c in claimants)
                conflicts.append((claimants[0]["verified"][pid][0].gamertag, who))
                for c in claimants:
                    c["verified"].pop(pid, None)

        # ---- pick targets
        for g in groups:
            ranked = sorted(
                g["verified"].values(),
                # untagged first, then the player with the most placements (the established "home"
                # identity), then epic-id evidence, then active -- placements outrank epic-id because
                # the sheet's id may belong to the thin LAN account rather than the home account.
                key=lambda pr: (not is_lan_tagged(pr[0]), _placement_count(db, pr[0].id), "epic-id" in pr[1], pr[0].is_active),
                reverse=True,
            )
            g["target"] = ranked[0][0] if ranked else None
            g["target_is_lan_only"] = bool(ranked) and is_lan_tagged(ranked[0][0])
            g["sources"] = [pr for pr in ranked[1:]]
        main_targets = {g["target"].id for g in groups if g["target"] is not None}

        # ---- optional (unverified) LAN candidates
        lan_pool = [
            (p, skeleton(p.gamertag), clean_gamertag(p.gamertag).casefold())
            for p in all_players
            # Thin active players (<= 2 placements). Not restricted to bracket-tagged names: after a
            # fresh re-sync (scripts/reset_roster.py) Osirion's tags are stripped at creation, so LAN
            # accounts are plain-named.
            if p.is_active and len(p.placement_results) <= 2
        ]
        claimed_ids = set(claims)
        for g in groups:
            taken = set(g["verified"]) | claimed_ids | main_targets
            probes = [skeleton(n) for n in g["names"]]
            if g["target"] is not None:
                probes.append(skeleton(g["target"].gamertag))
            pro_key = skeleton(g["pro"]) if len(_NON_ALNUM.sub("", g["pro"].casefold())) >= 4 else ""
            optionals = []
            for p, sk, _core in lan_pool:
                if p.id in taken or p.gamertag.startswith(_TOMBSTONE_PREFIX):
                    continue
                ratio = max((SequenceMatcher(None, sk, pr).ratio() for pr in probes if pr and not pr.startswith("raw:")), default=0.0)
                contains = bool(pro_key) and pro_key in sk
                if ratio >= _FUZZY_OPTIONAL_THRESHOLD or contains:
                    why = f"similarity {ratio:.2f}" + (f", contains pro name {g['pro']!r}" if contains else "")
                    optionals.append((max(ratio, 0.99 if contains else 0.0), p, why))
            optionals.sort(key=lambda t: t[0], reverse=True)
            g["optionals"] = [] if args.exact_only else optionals[:_MAX_OPTIONALS]

        import re as _re
        _optional_claims: dict = defaultdict(int)
        for g in groups:
            for _s, p, _why in g["optionals"]:
                _optional_claims[p.id] += 1

        def _auto_ok(why: str, p) -> bool:
            if args.auto_optionals is None or _optional_claims[p.id] != 1:
                return False
            m = _re.search(r"similarity ([0-9.]+)", why)
            return bool(m) and float(m.group(1)) >= args.auto_optionals

        # ---- report / merge
        stats = defaultdict(int)
        not_found, lan_only, nothing_to_merge, skipped_unsafe = [], [], [], []
        for g in groups:
            label = f"[{'/'.join(g['player_ids']) or '?'}] {g['pro']}"
            target = g["target"]
            if target is None:
                stats["not found"] += 1
                not_found.append(label)
                print("=" * 100)
                print(f"{label}: NOT FOUND in the database (no Epic-ID mapping, no exact-name match).")
                for _score, p, why in g["optionals"]:
                    print(f"    unverified look-alike (no main account to merge into): {p.gamertag!r}  ({why})")
                continue
            if g["target_is_lan_only"]:
                stats["lan only"] += 1
                lan_only.append(label)
            if not g["sources"] and not g["optionals"]:
                stats["nothing to merge"] += 1
                nothing_to_merge.append(label)
                continue

            print("=" * 100)
            print(f"{label}   sheet account(s): {', '.join(g['names']) or '(none)'}")
            if g["notes"]:
                print(f"    note: {g['notes']}")
            t_reasons = ", ".join(sorted(g["verified"][target.id][1]))
            print(f"    TARGET (main): id={target.id}  {target.gamertag!r}  placements={_placement_count(db, target.id)}  "
                  f"{'active' if target.is_active else 'INACTIVE'}   [{t_reasons}]"
                  + ("   (only LAN-tagged rows exist -- no untagged main account)" if g["target_is_lan_only"] else ""))
            for p, reasons in g["sources"]:
                print(f"    VERIFIED SOURCE: id={p.id}  {p.gamertag!r}  placements={_placement_count(db, p.id)}  "
                      f"{'active' if p.is_active else 'INACTIVE'}   [{', '.join(sorted(reasons))}]")
            for idx, (_s, p, why) in enumerate(g["optionals"], start=1):
                shared = f"  [offered to {_optional_claims[p.id]} pros -- never auto]" if _optional_claims[p.id] > 1 else ""
                print(f"    [{idx}] OPTIONAL (unverified): id={p.id}  {p.gamertag!r}  placements={_placement_count(db, p.id)}  "
                      f"({why}){'  [auto]' if _auto_ok(why, p) else ''}{shared}")

            if not g["sources"] and not g["optionals"]:
                continue
            if not args.confirm:
                stats["would merge"] += len(g["sources"])
                stats["would auto-merge optionals"] += sum(1 for _s, p, why in g["optionals"] if _auto_ok(why, p))
                continue

            if args.auto_optionals is not None:
                to_merge = [p for p, _ in g["sources"]] + [p for _s, p, why in g["optionals"] if _auto_ok(why, p)]
                if not to_merge:
                    print("  (auto) nothing qualifies for this pro.")
                    continue
                choice = "auto"
            else:
                to_merge = None
            hint = "Enter=merge verified source(s)" if g["sources"] else "no verified sources"
            opt_hint = ", numbers like 1,3 to ALSO merge optional candidates" if g["optionals"] else ""
            choice = choice if to_merge is not None else input(
                f"\n  {hint}{opt_hint}, 'n' to skip this pro, 'q' to quit: ").strip().lower()
            if choice == "q":
                print("Quitting -- no further pros processed.")
                break
            if choice == "n":
                print("  Skipped.")
                stats["skipped by you"] += 1
                continue

            if to_merge is None:
                to_merge = [p for p, _ in g["sources"]]
            if choice and choice not in ("y", "auto"):
                for tok in choice.replace(" ", "").split(","):
                    if tok.isdigit() and 1 <= int(tok) <= len(g["optionals"]):
                        to_merge.append(g["optionals"][int(tok) - 1][1])
                    elif tok:
                        print(f"  Ignoring {tok!r} (not a valid optional number).")
            if not to_merge:
                print("  Nothing selected.")
                continue

            for source in to_merge:
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

        print("\n" + "=" * 100)
        print("SUMMARY")
        for k in ("merged", "would merge", "would auto-merge optionals", "skipped by you", "skipped unsafe", "nothing to merge", "lan only", "not found"):
            if stats.get(k):
                print(f"  {k}: {stats[k]}")
        if conflicts:
            print(f"  {len(conflicts)} player(s) matched TWO different pros and were left alone (name coincidence):")
            for gamertag, who in conflicts:
                print(f"    {gamertag!r} claimed by {who}")
        if lan_only:
            print(f"  Only LAN-tagged rows exist for {len(lan_only)} pro(s) (no untagged main to merge into): "
                  + ", ".join(lan_only))
        if not_found:
            print(f"  Not found in the database at all ({len(not_found)}): " + ", ".join(not_found))
        if skipped_unsafe:
            print("  Left untouched because a real user holds/ordered/traded them:")
            for line in skipped_unsafe:
                print(f"    {line}")
        if not args.confirm:
            print("\nDry run only -- nothing changed. Re-run with --confirm to interactively apply merges.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
