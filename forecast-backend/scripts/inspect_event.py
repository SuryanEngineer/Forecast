#!/usr/bin/env python3
"""
List every Osirion window of events whose name matches, with what the format rules read from each: time, cash / paid places,
scoring, lobby type (set vs open, from the leaderboard size) and the pool the rules give it. Read-only.

    python scripts/inspect_event.py --match "Trios Cash Cup" --since 2026-11-01
    python scripts/inspect_event.py --match "Arenas" --since 2026-10-20 --max-lookups 20
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.engine import format_policy, tracking_policy  # noqa: E402
from app.integrations import osirion_client  # noqa: E402
from app.services import osirion_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", required=True, help="case-insensitive text in the event name / group / id")
    ap.add_argument("--since", default="2026-01-01", help="YYYY-MM-DD, windows beginning on/after this")
    ap.add_argument("--max-lookups", type=int, default=25, help="max leaderboard requests (lobby size checks)")
    args = ap.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    needle = tracking_policy.squash(args.match)
    db = SessionLocal()
    try:
        windows = osirion_service.list_available_windows(include_historic_data=True)
        rows = [
            w for w in windows
            if needle in tracking_policy.squash(w.classification_text)
            and (w.begin_time or w.end_time) is not None
            and (w.begin_time or w.end_time).astimezone(timezone.utc) >= since
        ]
        rows.sort(key=lambda w: w.begin_time or w.end_time)
        print(f"{len(rows)} window(s) match '{args.match}' since {args.since}\n")
        lookups = 0
        for w in rows:
            verdict, size = None, "-"
            if lookups < args.max_lookups and w.begin_time and w.begin_time <= datetime.now(timezone.utc):
                lookups += 1
                try:
                    page0 = osirion_client.get_leaderboard_page(w.leaderboard_event_id, w.leaderboard_event_window_id, 0)
                    n = len(page0.get("entries") or [])
                    pages = page0.get("totalPages") or 1
                    size = f"{n} on page 1 of {pages}"
                    verdict = tracking_policy.verdict_from_field(n, pages, n)
                except Exception as exc:  # noqa: BLE001
                    size = f"error: {exc}"
            rec = format_policy.decide(lobby=format_policy.lobby_label(verdict), has_cash=w.has_cash_payout, stage_index=1, scoring=w.scoring)
            print(f"{w.begin_time:%Y-%m-%d %H:%M}  {w.display_name}  [{','.join(w.regions)}]")
            print(f"    event={w.event_id}  window={w.event_window_id}  round={w.round}")
            print(f"    cash={'yes' if w.has_cash_payout else 'no'} (top ${float(w.top_cash_amount):,.0f}, pays {w.cash_places or '?'} places)  "
                  f"scoring={w.scoring}  field={size}  lobby={format_policy.lobby_label(verdict)}")
            print(f"    rules say: {format_policy.describe(rec) if rec else 'not tracked'}"
                  f"{'  pool param ' + rec['pool_param'] if rec else ''}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
