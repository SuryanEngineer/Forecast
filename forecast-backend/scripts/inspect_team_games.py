#!/usr/bin/env python3
"""
READ-ONLY: show the raw per-game data Osirion gave us for one team, so the game-by-game breakdown (GET
/tournaments/{id}/players/{player_id}/games) can be checked against the real key names.

    python3 scripts/inspect_team_games.py                      # newest finalized tournament, its #1 team
    python3 scripts/inspect_team_games.py --grep "Sep 25"      # tournament whose name contains this
    python3 scripts/inspect_team_games.py --placement 5
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grep", default="")
    ap.add_argument("--placement", type=int, default=1)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        q = db.query(Tournament).filter(Tournament.status == TournamentStatus.FINALIZED)
        if args.grep:
            q = q.filter(Tournament.name.ilike(f"%{args.grep}%"))
        t = q.order_by(Tournament.start_time.desc().nullslast()).first()
        if t is None:
            sys.exit("no matching finalized tournament")
        rows = db.query(PlacementResult).filter_by(tournament_id=t.id, placement=args.placement).all()
        print(f"{t.name}  (placement #{args.placement}: {len(rows)} player row(s))")
        for r in rows:
            p = db.get(Player, r.player_id)
            raw = r.raw_stats or {}
            print(f"\n== {p.gamertag}  team_id={r.team_id}")
            print("entry keys:", sorted(raw.keys()))
            sessions = raw.get("sessionHistory") or []
            print(f"sessionHistory: {len(sessions)} game(s)")
            for s in sessions[:2]:
                print(json.dumps(s, indent=2, default=str)[:1500])
            if raw.get("unscoredSessions"):
                print("unscoredSessions:", json.dumps(raw["unscoredSessions"], default=str)[:400])
            break  # teammates share the same entry
    finally:
        db.close()


if __name__ == "__main__":
    main()
