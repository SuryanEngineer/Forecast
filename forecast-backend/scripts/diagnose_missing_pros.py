#!/usr/bin/env python3
"""
READ-ONLY. Explains why sheet pros are "NOT FOUND" after merge_from_linker.py.

For every sheet pro that has no live player (no Epic-ID mapping, no alias, no player carrying a LAN name), this scans the
raw leaderboards we archived for EVERY tracked tournament (TournamentResultArchive) for that pro's Epic ID or any LAN
account name, and reports where they appear:

  * appears in an archive but has no player  -> the sync skipped them (or a cleanup script deleted them) -- tell me
  * appears nowhere                          -> the tournament we tracked simply doesn't contain them
                                               (e.g. they played a different EWC/Global window we didn't track)

It also lists the tracked LAN/global tournaments with field sizes, so you can see which windows we actually hold.

    python3 scripts/diagnose_missing_pros.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, PlayerAlias  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentResultArchive, TournamentType  # noqa: E402
from app.services.player_identity import norm_id, skeleton  # noqa: E402
from scripts.merge_from_linker import DEFAULT_FILE, build_groups, load_rows  # noqa: E402

_TOMB = "[MERGED INTO"


def main() -> None:
    groups = build_groups(load_rows(Path(DEFAULT_FILE)))
    db = SessionLocal()
    try:
        players = db.query(Player).all()
        by_id = {p.id: p for p in players}
        live_sk = {skeleton(p.gamertag) for p in players if not p.gamertag.startswith(_TOMB)}
        maps = {norm_id(m.osirion_account_id): m for m in db.query(OsirionPlayerMapping).all()}
        aliases = {a.alias_key for a in db.query(PlayerAlias).all()}

        def resolvable(g) -> bool:
            for i in g["epic_ids"]:
                m = maps.get(norm_id(i))
                if m is not None and m.player_id in by_id and not by_id[m.player_id].gamertag.startswith(_TOMB):
                    return True
            return any(skeleton(n) in live_sk or skeleton(n) in aliases for n in g["names"])

        missing = [g for g in groups if not resolvable(g)]
        print(f"{len(missing)} sheet pro(s) have no live player.\n")

        archives = db.query(Tournament, TournamentResultArchive).join(
            TournamentResultArchive, TournamentResultArchive.tournament_id == Tournament.id).all()
        counts = dict(db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).group_by(PlacementResult.tournament_id).all())

        print("Tracked LAN/global tournaments we hold:")
        for t, a in sorted(archives, key=lambda x: x[0].start_time or x[0].created_at):
            if t.tournament_type in (TournamentType.GLOBAL_CHAMPIONSHIP, TournamentType.MAJOR):
                ents = a.raw_leaderboard_entries or []
                n_players = sum(len(e.get("players", []) or []) for e in ents)
                print(f"  {str((t.start_time or t.created_at).date()):<11} {t.status.value:<16} {t.name}   "
                      f"archive players={n_players}  placements stored={counts.get(t.id, 0)}")

        index_id: dict = {}
        index_name: dict = {}
        for t, a in archives:
            for e in a.raw_leaderboard_entries or []:
                for pl in e.get("players", []) or []:
                    aid, un = pl.get("accountId"), pl.get("username")
                    if aid:
                        index_id.setdefault(norm_id(aid), []).append((t.name, e.get("rank"), un, aid))
                    if un:
                        index_name.setdefault(skeleton(un), []).append((t.name, e.get("rank"), un, aid))

        print("\nPer missing pro:")
        found_somewhere = 0
        for g in missing:
            hits = []
            for i in g["epic_ids"]:
                hits += [("epic-id",) + h for h in index_id.get(norm_id(i), [])]
            for n in g["names"]:
                hits += [("name",) + h for h in index_name.get(skeleton(n), [])]
            label = f"[{'/'.join(g['player_ids'])}] {g['pro']}"
            if not hits:
                print(f"  {label}: in NO archived leaderboard   (LAN names: {', '.join(g['names'])})")
                continue
            found_somewhere += 1
            print(f"  {label}: appears in an archive but has no player!")
            seen = set()
            for how, tname, rank, un, aid in hits:
                if (tname, aid) in seen:
                    continue
                seen.add((tname, aid))
                has_map = norm_id(aid) in maps if aid else False
                print(f"      {how}: {tname}  rank {rank}  as {un!r}  account={aid}  mapped={has_map}")
        print(f"\n{found_somewhere} of {len(missing)} appear in an archive; {len(missing) - found_somewhere} appear in none.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
