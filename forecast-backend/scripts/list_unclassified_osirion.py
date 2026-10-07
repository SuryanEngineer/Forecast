#!/usr/bin/env python3
"""
Read-only: show Osirion events that the backfill scan silently drops because NO classification rule matches
(the "237 unclassified" in track_missing_finals.py). Lists the 2026+ ones (--year) with the exact text a rule
would have to match, so you can see where EWC / FNCS Finals / etc. are hiding.

One row per event (its highest-paying window, same as the scan). Nothing is written.

    python3 scripts/list_unclassified_osirion.py
    python3 scripts/list_unclassified_osirion.py --year 2026 --min-payout 50000
    python3 scripts/list_unclassified_osirion.py --grep "world cup"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.services import osirion_service, tournament_classification_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=datetime.now().year, help="Only events beginning in this year or later.")
    ap.add_argument("--min-payout", type=float, default=0, help="Only events whose top cash payout is at least this.")
    ap.add_argument("--grep", default="", help="Only events whose name/group/id contains this text.")
    ap.add_argument("--include-no-cash", action="store_true",
                    help="Also list events with NO cash payout. The normal scan drops these entirely, which would hide "
                         "practice/qualifier-style events (e.g. FNCS Division 1 Practice).")
    ap.add_argument("--all", action="store_true", help="Also show classified + already-tracked events.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        windows = osirion_service.list_available_windows(include_historic_data=True)
        tracked = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in db.query(OsirionTournamentMapping).all()}
        by_event: dict[str, list] = {}
        for w in windows:
            by_event.setdefault(w.event_id, []).append(w)

        now = datetime.now(timezone.utc)
        rows = []
        for event_id, group in by_event.items():
            if args.include_no_cash:
                elig = [w for w in group if not w.is_zero_build]  # events with no cash payout (e.g. practice/qualifier)
            else:
                elig = [w for w in group if w.has_cash_payout and not w.is_zero_build]
            if not elig:
                continue
            w = max(elig, key=lambda x: x.top_cash_amount)
            when = w.begin_time or w.end_time
            if when is None or when.year < args.year or float(w.top_cash_amount) < args.min_payout:
                continue
            hay = f"{w.display_name} {w.event_group} {w.event_id}".lower()
            if args.grep and args.grep.lower() not in hay:
                continue
            hit = next((r for r in tournament_classification_service.get_active_rules(db)
                        if r.pattern.lower() in w.classification_text.lower()), None)
            ttype = hit.tournament_type if hit else None
            is_tracked = (w.leaderboard_event_id, w.leaderboard_event_window_id) in tracked
            if not args.all and (ttype is not None or is_tracked):
                continue
            end = w.end_time
            ended = end is not None and (end if end.tzinfo else end.replace(tzinfo=timezone.utc)) < now
            if is_tracked:
                tag = "tracked"
            elif hit is None:
                tag = "NO RULE MATCHES"
            elif ttype is None:
                tag = f"EXCLUDED:{hit.pattern}"
            else:
                tag = ttype.value
            rows.append((when, w, tag, ended))

        rows.sort(key=lambda r: r[0])
        for when, w, tag, ended in rows:
            print(f"{str(when.date()):<11} {tag:<28} ${float(w.top_cash_amount):>11,.0f} {'ended' if ended else 'open ':<5} "
                  f"{','.join(w.regions) or '-':<10} {w.display_name}\n"
                  f"{'':<11} group={w.event_group!r} event_id={w.event_id!r}")
        print(f"\n{len(rows)} event(s) shown.")
        counts: dict[str, int] = {}
        for _, _, tag, _ in rows:
            counts[tag] = counts.get(tag, 0) + 1
        for tag, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>4}  {tag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
