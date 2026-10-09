#!/usr/bin/env python3
"""
Put UPCOMING finals on the calendar before they start.

discover_finals.py only handles events that have already ended (it needs the finished leaderboard to check the lobby
size). This looks at events that have NOT finished yet and tracks the ones that qualify, so they appear on the
Tournaments calendar and the live loop syncs/pays them normally once they run.

An upcoming window qualifies when it passes the same structural checks as a finals (real-money cash prize >= --min-cash,
scoring has kill points AND placement points, PC platform, not Zero Build, region NAC/EU/ONSITE, 2026+) AND the
admin-editable classification rules give it a tier (rules that say "exclude" -- heats, performance evaluations, Victory
Cups -- or match nothing are skipped; the reason is printed). The lobby size is unknowable before it starts, so the live
sync has an open-field guard: if a tracked event turns out to have thousands of entries it is hidden immediately and no
players are created.

Dry run by default.

    python3 scripts/track_upcoming_finals.py
    python3 scripts/track_upcoming_finals.py --grep "Division"
    python3 scripts/track_upcoming_finals.py --confirm
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import TournamentType  # noqa: E402
from app.services import osirion_service, tournament_classification_service  # noqa: E402
from scripts.discover_finals import build_parser, collect_cheap_pass  # noqa: E402


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    args.include_upcoming = True
    regions = {r.upper() for r in args.regions}
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        print("Fetching Osirion tournament details ...")
        windows = osirion_service.list_available_windows(include_historic_data=False)
        tracked = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in db.query(OsirionTournamentMapping).all()}
        rules = tournament_classification_service.get_active_rules(db)

        def upcoming(w) -> bool:
            end = w.end_time
            return end is None or (end if end.tzinfo else end.replace(tzinfo=timezone.utc)) >= now

        windows = [w for w in windows if upcoming(w)]
        cheap, failed, n_events = collect_cheap_pass(windows, args, regions, now, rules)
        print(f"{len(windows)} upcoming/in-progress window(s) in {n_events} event(s); {len(cheap)} pass cash+scoring+scope.\n")

        to_track, skipped = [], []
        for w, hit, cash, summary in sorted(cheap, key=lambda t: t[0].begin_time or t[0].end_time):
            key = (w.leaderboard_event_id, w.leaderboard_event_window_id)
            when = (w.begin_time or w.end_time)
            if key in tracked:
                skipped.append((w, "already tracked"))
                continue
            ttype = hit.tournament_type if hit is not None else None
            if ttype is None:
                ttype = tournament_classification_service.classify(db, w.classification_text)
            if ttype is None:
                skipped.append((w, "no classification rule matches (add one, or it is not a finals)"))
                continue
            to_track.append((w, ttype, cash, summary))

        print(f"WOULD TRACK ({len(to_track)}):")
        for w, ttype, cash, summary in to_track:
            print(f"  {str((w.begin_time or w.end_time).date()):<11} {ttype.value:<20} ${float(cash):>10,.0f}  {summary}  {w.display_name}  [{w.event_group}]")
        print(f"\nSKIPPED ({len(skipped) + len(failed)}):")
        for w, why in skipped + failed:
            d = w.begin_time or w.end_time
            print(f"  {str(d.date()) if d else '?':<11} {w.display_name}  [{why}]")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to put the WOULD TRACK rows on the calendar.")
            return
        for w, ttype, cash, summary in to_track:
            region = w.regions[0] if len(w.regions) == 1 else None
            osirion_service.track_tournament(
                db, name=w.display_name, tournament_type=ttype, region=region,
                window=w, created_by_admin_id=None, is_historical_archive=False,
            )
            print(f"tracked: {w.display_name}")
        print(f"\nTracked {len(to_track)}. The live loop syncs each once it starts and finalizes it (with dividends) when it ends.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
