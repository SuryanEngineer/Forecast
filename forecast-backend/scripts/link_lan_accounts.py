#!/usr/bin/env python3
"""
Resolve LAN/global-event accounts the sync could not attach to a player.

Background: for LAN/global-tier tournaments (EWC, Global Championship, Majors) a LIVE sync does NOT auto-create
players for unrecognised accounts and will not FINALIZE (pay dividends) while any exist -- see
osirion_service._lan_hold_applies. An account is "recognised" if its Epic account id is already mapped to a player
(OsirionPlayerMapping) or its name matches a registered alias (PlayerAlias, filled from the linker sheet by
scripts/merge_from_linker.py). Anything else shows up here.

For each unrecognised account this lists its in-event name + rank and the most similar existing players, and you choose:
    <number>   link it to that player (stores the account id AND its name as an alias)
    n          it is a genuinely new person: create a new player (you can type the display name)
    s          skip for now
    q          quit
Once linked, the live loop's next pass (<= 45 s) attaches the placement and finalizes the tournament by itself.

Reads the raw leaderboard the sync archived (TournamentResultArchive), so it needs no Osirion calls.

    python3 scripts/link_lan_accounts.py --list              # just show what is unlinked
    python3 scripts/link_lan_accounts.py                     # interactive
    python3 scripts/link_lan_accounts.py --grep "Global"     # restrict to tournaments whose name contains this
    python3 scripts/link_lan_accounts.py --include-finalized # also inspect finished LAN tournaments
"""
from __future__ import annotations

import argparse
import sys
from difflib import SequenceMatcher

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, PlayerAlias  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentResultArchive, TournamentStatus, TournamentType  # noqa: E402
from app.services import player_service  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402
from app.services.player_identity import lan_core_keys, norm_id, skeleton  # noqa: E402

LAN_TYPES = (TournamentType.GLOBAL_CHAMPIONSHIP, TournamentType.MAJOR)
_TOMB = "[MERGED INTO"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="Only list; no prompts, no writes.")
    ap.add_argument("--grep", default="", help="Only tournaments whose name contains this text.")
    ap.add_argument("--include-finalized", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        q = db.query(Tournament).filter(Tournament.tournament_type.in_(LAN_TYPES))
        if not args.include_finalized:
            q = q.filter(Tournament.status != TournamentStatus.FINALIZED)
        if args.grep:
            q = q.filter(func.lower(Tournament.name).like(f"%{args.grep.lower()}%"))
        tournaments = q.order_by(Tournament.start_time.asc().nullslast()).all()
        if not tournaments:
            print("No matching LAN/global tournaments" + ("" if args.include_finalized else " that are still open (try --include-finalized)") + ".")
            return

        mapped = {norm_id(a) for (a,) in db.query(OsirionPlayerMapping.osirion_account_id).all()}
        aliases = {a.alias_key: a for a in db.query(PlayerAlias).all()}
        players = [p for p in db.query(Player).filter(~Player.gamertag.startswith(_TOMB)).all()]
        pool = [(p, skeleton(p.gamertag)) for p in players]
        alias_pool = [(a, k) for k, a in aliases.items()]

        total_unlinked = 0
        for t in tournaments:
            archive = db.query(TournamentResultArchive).filter_by(tournament_id=t.id).one_or_none()
            entries = (archive.raw_leaderboard_entries if archive else None) or []
            unknown: dict = {}
            for e in entries:
                rank = e.get("rank")
                for pl in e.get("players", []) or []:
                    aid, uname = pl.get("accountId"), pl.get("username")
                    if not aid or norm_id(aid) in mapped:
                        continue
                    if uname and skeleton(uname) in aliases:
                        continue  # the next sync auto-links this one by alias
                    unknown[aid] = (uname, rank)
            n_pl = db.query(func.count(PlacementResult.id)).filter(PlacementResult.tournament_id == t.id).scalar()
            print("=" * 100)
            print(f"{t.name}   [{t.status.value}]   placements stored: {n_pl}   unlinked accounts: {len(unknown)}")
            total_unlinked += len(unknown)

            for aid, (uname, rank) in sorted(unknown.items(), key=lambda kv: (kv[1][1] is None, kv[1][1] or 0)):
                label = uname or "(no username)"
                print(f"\n  #{rank}  {label}   account={aid}")
                key = skeleton(uname) if uname else ""
                sugg = []
                if key:
                    # Exact "core name" match first: "[EWC2026] HAVOK SwizzY" -> core "swizzy" == player "SwizzY".
                    core = lan_core_keys(uname)
                    for p, sk in pool:
                        if sk in core and sk != key:
                            sugg.append((1.0, p, f"{p.gamertag} (same name without team prefix)"))
                    for p, sk in pool:
                        r = SequenceMatcher(None, key, sk).ratio()
                        if r >= 0.55:
                            sugg.append((r, p, p.gamertag))
                    for a, k in alias_pool:
                        r = SequenceMatcher(None, key, k).ratio()
                        if r >= 0.55 and a.player is not None and not a.player.gamertag.startswith(_TOMB):
                            sugg.append((r, a.player, f"{a.player.gamertag} (alias {a.alias_name!r})"))
                seen, ranked = set(), []
                for r, p, shown in sorted(sugg, key=lambda x: x[0], reverse=True):
                    if p.id in seen:
                        continue
                    seen.add(p.id)
                    ranked.append((r, p, shown))
                ranked = ranked[:5]
                for i, (r, p, shown) in enumerate(ranked, start=1):
                    print(f"     [{i}] {shown!r}  similarity {r:.2f}  placements={len(p.placement_results)}")
                if not ranked:
                    print("     (no similar existing player)")
                if args.list:
                    continue
                choice = input("     number = link to that player, 'n' = new player, 's' = skip, 'q' = quit: ").strip().lower()
                if choice == "q":
                    print("Quitting.")
                    db.rollback()
                    return
                target = None
                if choice.isdigit() and 1 <= int(choice) <= len(ranked):
                    target = ranked[int(choice) - 1][1]
                elif choice == "n":
                    default = clean_gamertag(uname) if uname else ""
                    name = input(f"     display name for the new player [{default}]: ").strip() or default
                    if not name:
                        print("     No name -- skipped.")
                        continue
                    clash = db.query(Player).filter(func.lower(Player.gamertag) == name.casefold()).first()
                    if clash is not None:
                        print(f"     A player named {clash.gamertag!r} already exists -- link to it instead. Skipped.")
                        continue
                    target = player_service.create_player(db, gamertag=name)
                else:
                    print("     Skipped.")
                    continue
                db.add(OsirionPlayerMapping(osirion_account_id=aid, osirion_username=uname, player_id=target.id))
                if key and key not in aliases:
                    row = PlayerAlias(alias_key=key, alias_name=clean_gamertag(uname)[:200], player_id=target.id, source="manual-link")
                    db.add(row)
                    aliases[key] = row
                db.commit()
                mapped.add(norm_id(aid))
                print(f"     Linked -> {target.gamertag!r}")

        print("\n" + "=" * 100)
        print(f"Unlinked accounts found: {total_unlinked}")
        if args.list and total_unlinked:
            print("Run without --list to resolve them. Open LAN tournaments will not finalize until this is 0.")
        elif total_unlinked == 0:
            print("Nothing to link -- the live loop will finalize on its next pass if the window has ended.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
