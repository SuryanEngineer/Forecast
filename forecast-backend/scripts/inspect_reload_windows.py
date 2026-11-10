#!/usr/bin/env python3
"""
Read-only: list every Osirion window (including history and upcoming) that looks like part of the Reload family, with
what the tracking policy decides for it and why. Use it to check that FNCS Solo Reload Heats / Last Chance Qualifier /
Finals are recognised.

    python3 scripts/inspect_reload_windows.py              # every FNCS-ish Reload window
    python3 scripts/inspect_reload_windows.py --all-reload # every Reload window (any name)
    python3 scripts/inspect_reload_windows.py --no-field   # skip the leaderboard size lookups (no extra requests)
"""
from __future__ import annotations

import argparse
import sys
from datetime import timezone

sys.path.insert(0, ".")

from app.engine import tracking_policy  # noqa: E402
from app.integrations import osirion_client  # noqa: E402
from app.integrations.osirion_client import OsirionApiError  # noqa: E402
from app.services import osirion_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all-reload", action="store_true")
    ap.add_argument("--no-field", action="store_true")
    ap.add_argument("--max-lookups", type=int, default=40)
    args = ap.parse_args()

    windows = osirion_service.list_available_windows(include_historic_data=True)
    rows = []
    for w in windows:
        text = f"{w.classification_text} {w.raw_event_window.get('playlistId', '')}"
        s = tracking_policy.squash(text)
        if "reload" not in s:
            continue
        if not args.all_reload and "fncs" not in s:
            continue
        rows.append(w)
    rows.sort(key=lambda w: w.begin_time or w.end_time or 0)
    print(f"{len(rows)} Reload window(s)\n")
    lookups = 0
    for w in rows:
        text = f"{w.classification_text} {w.raw_event_window.get('playlistId', '')}"
        role = tracking_policy.reload_family_role(text)
        field = ""
        if role == tracking_policy.ROLE_QUALIFIER and not args.no_field and lookups < args.max_lookups and w.end_time and w.leaderboard_event_id:
            lookups += 1
            try:
                p0 = osirion_client.get_leaderboard_page(w.leaderboard_event_id, w.leaderboard_event_window_id, 0)
                n = len(p0.get("entries") or [])
                pages = int(p0.get("totalPages") or 1)
                field = f"entries/page={n} pages={pages} -> {tracking_policy.verdict_from_field(n, pages, n)}"
            except OsirionApiError as exc:
                field = f"leaderboard error: {exc}"
        plats = ",".join(str(p) for p in (w.raw_tournament.get("platforms") or []))
        print(f"{(w.begin_time.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') if w.begin_time else '?'):<17} role={role or '-':<9} "
              f"cash={'Y' if w.has_cash_payout else 'N'} zb={'Y' if w.is_zero_build else 'N'} regions={','.join(w.regions) or '-'} "
              f"platform={osirion_service.platform_restriction(w) or 'ok'}")
        print(f"    name: {w.display_name}\n    event_id: {w.event_id}  group: {w.event_group}  platforms: {plats}")
        if field:
            print(f"    field: {field}")
        print()


if __name__ == "__main__":
    main()
