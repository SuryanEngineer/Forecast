#!/usr/bin/env python3
"""
Read-only fuzzy-match search (makes ZERO writes) for the handful of
duplicate groups that scripts/merge_duplicate_players.py's EXACT
clean_gamertag() matching found only LAN-tagged rows for (e.g. just
"[EWC2026] X" and "[FNCSGC26] X", no untagged "regular season" row at
all, active or inactive).

Why this exists: an exact match can't catch a genuine typo between how
two different circuits' organizers entered the same real person's name
(EWC's own registration vs. FNCS's). This does NOT mean such a row is
being missed by merge_duplicate_players.py -- that script already scans
every Player regardless of active status, so if an exact-spelled row
existed anywhere in this database it WOULD already be in the group. This
script exists purely to rule out (or find) a near-miss SPELLING variant
exact matching structurally cannot catch.

For every active player whose gamertag starts with a bracketed LAN/circuit
tag (e.g. "[EWC2026] ...", "[FNCSGC26] ...") and has very few placements
(<=2 -- i.e. looks like a one-off LAN appearance, not an established
"home" identity), this strips the tag and fuzzy-compares the remaining
name (case-insensitive) against every OTHER player in the database (any
status), reporting anything above a similarity threshold that ISN'T
already an exact match (those are merge_duplicate_players.py's job).

This is read-only and changes nothing -- it's purely to tell you, with
real data, whether "the regular-season row exists here under a typo'd
name" or "it genuinely was never tracked in this database" for the
remaining two-LAN-tag-only groups.

Usage:
    cd forecast-backend
    python3 scripts/find_near_miss_matches.py
    python3 scripts/find_near_miss_matches.py --threshold 0.75   # looser match
"""
from __future__ import annotations

import argparse
import re
import sys
from difflib import SequenceMatcher

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402

_TOURNAMENT_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")


def _strip_leading_tag(gamertag: str) -> str:
    """Just the leading bracket tag (e.g. "[EWC2026] ") -- clean_gamertag()
    already strips ALL bracket segments anywhere in the string; this is
    narrower; used here only to decide which players look like "a one-off
    LAN appearance" in the first place."""
    return _TOURNAMENT_TAG_RE.sub("", gamertag).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float, default=0.82,
                         help="Minimum similarity ratio (0-1) to report as a near-miss candidate. Default 0.82.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        all_players = db.query(Player).filter(~Player.gamertag.startswith("[MERGED INTO")).all()

        needles = [
            p for p in all_players
            if p.is_active
            and p.gamertag.startswith("[")
            and len(db_placements := p.placement_results) <= 2  # noqa: F841 -- name kept for clarity, see below
        ]
        # (placement_results is a lazy relationship -- fine for this small
        # needle set; NOT used on the much larger haystack below.)

        if not needles:
            print("No active LAN-tagged, low-placement players found -- nothing to check.")
            return

        print(f"Checking {len(needles)} active LAN-tagged candidate(s) against {len(all_players)} total player(s) "
              f"for near-miss (non-exact) spelling matches, threshold={args.threshold}...\n")

        haystack = [(p, clean_gamertag(p.gamertag).lower()) for p in all_players]

        found_any = False
        for needle in needles:
            needle_core = clean_gamertag(needle.gamertag).lower()
            best_matches = []
            for other, other_core in haystack:
                if other.id == needle.id or other_core == needle_core:
                    continue  # self, or already an exact match (merge_duplicate_players.py's job)
                ratio = SequenceMatcher(None, needle_core, other_core).ratio()
                if ratio >= args.threshold:
                    best_matches.append((ratio, other))
            if best_matches:
                found_any = True
                best_matches.sort(key=lambda t: t[0], reverse=True)
                print(f"  {needle.gamertag!r} (id={needle.id}) -- possible near-miss match(es):")
                for ratio, other in best_matches[:5]:
                    status = "active" if other.is_active else "inactive"
                    pcount = len(other.placement_results)
                    print(f"    ratio={ratio:.2f}  id={other.id}  gamertag={other.gamertag!r}  "
                          f"status={status}  placements={pcount}")

        if not found_any:
            print("No near-miss spelling candidates found above threshold. This is real evidence (not just an "
                  "absence of searching) that the remaining two-LAN-tag-only groups' regular-season identity "
                  "was genuinely never tracked in this database -- not that it exists here under a different name.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
