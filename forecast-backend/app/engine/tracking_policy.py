"""
Which Osirion windows this platform tracks -- the pure (no DB, no network) part of the rules.

Product rules (Nov 2026):
  * Only Battle Royale (build) and Reload are tracked. Zero Build is never tracked.
  * A window is tracked if it pays real cash (Cash Cups, Finals, ...) OR it is a SET-LOBBY qualifier of a tracked
    event family (a fixed, invited field -- not an open round anyone can enter).
  * FNCS Solo Reload family: "Heats" / "Last Chance Qualifier" sessions are qualifiers (tier FNCS_QUALIFIER, tracked
    only when set-lobby); the "Finals" is FNCS_FINALS (full FNCS pool, trusted even before Osirion publishes cash).
  * Open rounds (tens of thousands of entrants) are never tracked as tournaments; they are only browsable (see
    app/services/open_rounds_service.py).

Text is matched "squashed" (lower-cased, punctuation/spaces removed) because Osirion writes the same event as
"FNCS Solo Reload Finals", "S41_FNCS_SoloReload_Finals", "FNCSSoloReloadFinals", ...
"""
from __future__ import annotations

import re

# A set lobby is a few dozen to ~200 teams. Anything with more entries than this is an open round.
SET_LOBBY_MAX_ENTRIES = 250

ROLE_FINAL = "final"
ROLE_QUALIFIER = "qualifier"
ROLE_OPEN = "open"

_QUALIFIER_WORDS = ("lastchance", "heat", "qualif", "semifinal")


def squash(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def is_fncs_reload_family(text: str | None) -> bool:
    s = squash(text)
    return "fncs" in s and "reload" in s


def reload_family_role(text: str | None) -> str | None:
    """Role of a window inside the FNCS Reload family: 'final', 'qualifier' (heats / last chance / semifinal), 'open'
    (an open round), or None when the text is not FNCS Reload at all or its role is unclear."""
    if not is_fncs_reload_family(text):
        return None
    s = squash(text)
    if any(w in s for w in _QUALIFIER_WORDS):
        return ROLE_OPEN if "open" in s else ROLE_QUALIFIER
    if "final" in s:
        return ROLE_FINAL
    if "open" in s:
        return ROLE_OPEN
    return None


def looks_like_open_round(text: str | None) -> bool:
    """Name says open round (e.g. 'Open Round 1', 'Open Heat')."""
    return "open" in squash(text)


def reload_region_ok(regions: list[str], allowed: set[str]) -> bool:
    """FNCS Reload events may be listed with several regions (or none); accept when unrestricted or any allowed region
    is involved. A single-region event must be an allowed region."""
    upper = [r.strip().upper() for r in regions if r]
    if not upper:
        return True
    return any(r in allowed for r in upper)


def verdict_from_field(entries: int | None, total_pages: int | None, per_page: int | None) -> bool | None:
    """True = set lobby, False = open round, None = cannot tell yet (empty leaderboard, e.g. not started).
    Uses the first leaderboard page only: more than one page of a typical page size is already an open field."""
    if entries is None:
        return None
    if entries == 0:
        return None
    pages = total_pages or 1
    size = per_page or entries
    if pages > 1:
        approx = size * (pages - 1) + 1
        return approx <= SET_LOBBY_MAX_ENTRIES
    return entries <= SET_LOBBY_MAX_ENTRIES


def cluster_by_gap(items: list, start_of, end_of, max_gap_hours: float = 36.0) -> list[list]:
    """Group windows of one event into editions: consecutive windows less than `max_gap_hours` apart belong together
    (a multi-day final), a longer gap starts a new edition (weekly cups reuse one event id)."""
    from datetime import datetime, timezone

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _aware(d):
        return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)

    dated = sorted(items, key=lambda x: _aware(start_of(x)) or _aware(end_of(x)) or epoch)
    clusters: list[list] = []
    prev_end = None
    for item in dated:
        begin = start_of(item)
        end = end_of(item) or begin
        if clusters and begin is not None and prev_end is not None and (begin - prev_end).total_seconds() / 3600.0 < max_gap_hours:
            clusters[-1].append(item)
        else:
            clusters.append([item])
        if end is not None and (prev_end is None or end > prev_end):
            prev_end = end
    return clusters
