#!/usr/bin/env python3
"""
Read-only diagnostic (ZERO writes) explaining why
scripts/merge_qualified_duplicates.py found 0 players with a real placement
in a GC-qualifying tournament type (MAJOR / FNCS_FINALS / FNCS_QUALIFIER).

Two possible causes, and this script tells you which one it actually is:

  (a) A classification-rule gap -- same bug class already found and fixed
      once for "global championship" (see
      tournament_classification_service.py's DEFAULT_RULES comment: a real
      $2,000,000 Global Championship LAN window matched no rule at all
      because Osirion splits the "FNCS" branding into eventGroup separately
      from the title). The only rule that can ever produce FNCS_FINALS is
      the literal substring "fncs finals" in `display_name eventGroup
      eventId` combined -- if real FNCS Major/Finals windows don't happen
      to contain that exact adjacent phrase, they fall through to "no rule
      matched" and are silently never auto-tracked, OR get caught by an
      earlier, more general rule (e.g. "fncs division" -> CASH_CUP) instead.

  (b) Real data gap -- the regular FNCS season for 2026 (Major 1, Major 2,
      Last Chance) genuinely has no tracked tournaments at all, e.g. because
      auto-tracking wasn't live yet when those windows were open, or they
      fell in a region this app doesn't track.

This prints every tournament whose name contains "fncs" (any case),
alongside its tournament_type and placement count, so you can see directly
which of the two it is.

Usage:
    cd forecast-backend
    python3 scripts/inspect_fncs_classification.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        tournaments = (
            db.query(Tournament)
            .filter(Tournament.name.ilike("%fncs%"))
            .order_by(Tournament.start_time.desc().nullslast())
            .all()
        )

        if not tournaments:
            print("No tournament in this database has 'fncs' anywhere in its name at all.")
            print("That means the regular FNCS season (Major 1, Major 2, Last Chance, Division Finals) has "
                  "never been tracked here under any name -- a real data gap, not a classification bug. The "
                  "FNCSGC-tagged LAN duplicates genuinely have no regular-season identity to merge into.")
            return

        print(f"Found {len(tournaments)} tournament(s) with 'fncs' in the name:\n")
        by_type: dict[str, int] = {}
        for t in tournaments:
            pcount = db.query(PlacementResult).filter(PlacementResult.tournament_id == t.id).count()
            by_type[t.tournament_type.value] = by_type.get(t.tournament_type.value, 0) + 1
            print(f"  - {t.name!r}")
            print(f"      type={t.tournament_type.value}  region={t.region}  "
                  f"start={t.start_time}  placements={pcount}")

        print("\nBreakdown by tournament_type:")
        for ttype, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
            print(f"  {ttype}: {count}")

        if by_type.get("major", 0) == 0 and by_type.get("fncs_finals", 0) == 0 and by_type.get("fncs_qualifier", 0) == 0:
            print("\nNone of these are classified as major / fncs_finals / fncs_qualifier -- confirms this is a "
                  "classification-rule gap (cause (a) above), not a real data gap. The actual FNCS Major/Finals "
                  "windows are being caught by an earlier, more general rule (most likely 'fncs division' -> "
                  "CASH_CUP, since that pattern matches ANY name containing both 'fncs' and 'division') or are "
                  "falling through to 'no rule matched' and never being tracked at all. Share this output and I'll "
                  "write the exact classification-rule fix.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
