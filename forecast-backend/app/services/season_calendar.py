"""
The Fortnite season calendar the platform runs on. One row in `seasons` per Fortnite season / mini-season; the ranked
ladder (Seasonal Points) follows it, the website shows the current one, and price charts mark where each one begins.

Only seasons from "now" on matter (nothing earlier is tracked). Times are UTC at midnight unless you set a precise
changeover time:   python3 scripts/manage_seasons.py set "<name>" --starts 2026-12-05T09:00

Each season ends exactly when the next begins (Fortnite changes over in one step), so a season's end date here is the
START of the next season. A season with `ends=None` is open-ended until Epic announces the end: it runs until the next
season is added/begins, or until you run   python3 scripts/manage_seasons.py set "<name>" --ends YYYY-MM-DD

Edit FORTNITE_CALENDAR when Epic announces a new season (or use scripts/manage_seasons.py create/set), then run
    python3 scripts/manage_seasons.py sync-calendar
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.account import Season
from app.services import season_service


def _d(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# name, kind, starts, ends (None = TBD)
FORTNITE_CALENDAR: list[dict] = [
    {"name": "Chapter 7: Season 4 (Override)", "kind": "season", "starts": _d(2026, 8, 20), "ends": _d(2026, 11, 1)},
    {"name": "Mini-Season (Treasure Hunters)", "kind": "mini", "starts": _d(2026, 11, 1), "ends": _d(2026, 12, 5)},
    {"name": "Chapter 8: Season 1", "kind": "season", "starts": _d(2026, 12, 5), "ends": None},
]


def sync_calendar(db: Session, calendar: list[dict] | None = None) -> list[str]:
    """Create any season missing from the DB and bring un-finalized ones in line with the calendar, then run the
    rollover so the right one is active. Idempotent. Returns what it did."""
    actions: list[str] = []
    for item in (calendar if calendar is not None else FORTNITE_CALENDAR):
        row = db.query(Season).filter(Season.name == item["name"]).first()
        if row is None:
            season_service.create_season(db, item["name"], item["starts"], item["ends"], activate=False, kind=item["kind"])
            actions.append(f"created '{item['name']}'")
            continue
        if row.finalized_at is not None:
            continue
        changed = []
        if _cmp(row.starts_at) != _cmp(item["starts"]):
            row.starts_at = item["starts"]; changed.append("start")
        if _cmp(row.ends_at) != _cmp(item["ends"]):
            row.ends_at = item["ends"]; changed.append("end")
        if row.kind != item["kind"]:
            row.kind = item["kind"]; changed.append("kind")
        if changed:
            actions.append(f"updated '{row.name}' ({', '.join(changed)})")
    db.flush()
    actions.extend(season_service.run_rollover(db))
    names = {i["name"] for i in (calendar if calendar is not None else FORTNITE_CALENDAR)}
    for other in db.query(Season).filter(Season.finalized_at.is_(None), Season.is_active.is_(True)).all():
        if other.name not in names:
            actions.append(f"WARNING: active season '{other.name}' is not on the calendar -- delete it with "
                           f"`manage_seasons.py delete \"{other.name}\" --confirm`, then run sync-calendar again")
    return actions


def _cmp(dt: datetime | None):
    if dt is None:
        return None
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
