#!/usr/bin/env python3
"""
READ-ONLY coverage check: does the database contain EVERY tournament that Osirion says is a finals?

It applies the exact same rules as discover_finals.py (cash prize + kill AND placement scoring + finals-sized lobby,
2026+, NAC/EU/ONSITE, not Zero Build, no console/mobile-only, not Performance Evaluation / Victory Cup / heats) to
Osirion's full listing, then looks each result up in your DB and reports one status per tournament:

    OK        tracked, FINALIZED, has placements, visible
    PENDING   tracked but not FINALIZED yet (run sync_pending_tournaments.py --confirm)
    EMPTY     FINALIZED but 0 placements (re-pull needed)
    HIDDEN    finalized but flagged hidden (is_historical_archive)
    MISSING   Osirion says it is a finals, but it is not in the DB (run discover_finals.py --confirm)

It also lists DB tournaments from this year that do NOT match the rules ("extras"), and upcoming events that will
qualify once they end. Nothing is written.

    python3 scripts/verify_coverage.py
    python3 scripts/verify_coverage.py --grep division
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402
from app.services import osirion_service, tournament_classification_service  # noqa: E402
from scripts.discover_finals import build_parser, collect_cheap_pass, field_size, is_reload  # noqa: E402


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    regions = {r.upper() for r in args.regions}
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        print("Fetching Osirion tournament details (incl. history) ...")
        windows = osirion_service.list_available_windows(include_historic_data=True)
        rules = tournament_classification_service.get_active_rules(db)
        cheap, failed, n_events = collect_cheap_pass(windows, args, regions, now, rules)

        rows = (
            db.query(OsirionTournamentMapping, Tournament)
            .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
            .all()
        )
        by_key = {(m.leaderboard_event_id, m.leaderboard_event_window_id): (m, t) for m, t in rows}
        counts = dict(db.query(PlacementResult.tournament_id, func.count(PlacementResult.id))
                      .group_by(PlacementResult.tournament_id).all())

        expected_keys = set()
        report = []
        for w, hit, cash, summary in sorted(cheap, key=lambda t: t[0].begin_time or t[0].end_time):
            key = (w.leaderboard_event_id, w.leaderboard_event_window_id)
            when = (w.begin_time or w.end_time).date()
            if key in by_key:
                m, t = by_key[key]
                n = counts.get(t.id, 0)
                if t.status != TournamentStatus.FINALIZED:
                    status = "PENDING"
                elif n == 0:
                    status = "EMPTY"
                elif t.is_historical_archive:
                    status = "HIDDEN"
                else:
                    status = "OK"
                expected_keys.add(key)
                report.append((when, status, n, w.display_name, w.event_group))
            else:
                entries, players, note = field_size(w)
                size = players if players else entries
                cap = args.max_reload if is_reload(w) else args.max_br
                if entries is None or size > cap or size < args.min_field:
                    continue  # open/qualifier-sized lobby: not a finals, correctly absent
                report.append((when, "MISSING", 0, w.display_name, w.event_group))

        order = {"MISSING": 0, "PENDING": 1, "EMPTY": 2, "HIDDEN": 3, "OK": 4}
        print(f"\n{'date':<11} {'status':<8} {'placements':>10}  tournament")
        for when, status, n, name, group in sorted(report, key=lambda r: (order[r[1]], r[0])):
            print(f"{str(when):<11} {status:<8} {n:>10}  {name}  [{group}]")

        tally: dict[str, int] = {}
        for _, status, *_ in report:
            tally[status] = tally.get(status, 0) + 1
        print("\nSUMMARY: " + "   ".join(f"{k}={v}" for k, v in sorted(tally.items(), key=lambda kv: order[kv[0]])) +
              f"   (expected finals total: {len(report)})")

        extras = [(t, m) for (k, (m, t)) in by_key.items()
                  if k not in expected_keys and (t.start_time or t.created_at).year >= args.min_year]
        print(f"\nTRACKED IN DB BUT NOT MATCHING THE RULES ({len(extras)}) -- not necessarily wrong "
              f"(e.g. tracked earlier by name rules, a heat, or a no-cash window):")
        for t, m in sorted(extras, key=lambda x: x[0].start_time or x[0].created_at):
            print(f"  {str((t.start_time or t.created_at).date()):<11} {t.status.value:<16} "
                  f"{counts.get(t.id, 0):>5} placements  {t.name}")

        upcoming = [(w, why) for (w, why) in failed if why == "not ended yet"]
        print(f"\nUPCOMING (will qualify only if they pass the rules once finished): {len(upcoming)}")
        for w, _ in sorted(upcoming, key=lambda x: x[0].begin_time or x[0].end_time):
            print(f"  {str((w.begin_time or w.end_time).date()):<11} {w.display_name}")

        print("\nHow to read this: MISSING -> run discover_finals.py --confirm; PENDING/EMPTY -> sync_pending_tournaments.py "
              "--confirm; HIDDEN -> tell me. If an event you expect is in none of these lists, it fails a rule: run "
              "discover_finals.py --show-failed --grep \"<name>\" to see which one.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
