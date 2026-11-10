"""
Open qualifier rounds: browse them, search them -- but never track them.

An "open round" is a qualifier anyone can enter (tens of thousands of teams, no cash payout). They are NOT tournaments: no
dividends, no roster growth, no payouts. They are shown only for the families the platform tracks (the FNCS Reload family and
the heats of tracked cash events), never for Zero Build or console/mobile-only events.

Osirion has no search endpoint and no way to filter a leaderboard, so:
  * LIVE / any round: a cached page proxy (`get_page`) -- one Osirion request per page, cached, and capped per minute so it can
    never starve the tournament sync loop (they share Osirion's 45 requests/minute budget).
  * FINISHED rounds: a throttled background pass (`index_pass`, a couple of pages per sync cycle) stores the top of each recently
    finished round -- name, rank, points -- in a small table that `search` queries. Rounds older than INDEX_DAYS are dropped and
    each round is read only as deep as INDEX_MAX_PAGES, so the table stays small. Search says honestly how deep it covers.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.ttl_cache import cached_call
from app.engine import tracking_policy
from app.integrations import osirion_client
from app.integrations.osirion_client import OsirionApiError
from app.models.open_round import OpenRoundEntry, OpenRoundIndexState
from app.models.osirion import OsirionTournamentMapping
from app.services import osirion_service

logger = logging.getLogger("forecast.open_rounds")

LIST_CACHE_SECONDS = 300
LIVE_PAGE_CACHE_SECONDS = 60
FINISHED_PAGE_CACHE_SECONDS = 1800
LIVE_FETCHES_PER_MINUTE = 20   # uncached proxy fetches allowed per minute, across all visitors
INDEX_DAYS = 21                # finished rounds newer than this are indexed
INDEX_MAX_PAGES = 40           # deepest page read per round (the top of the field)
INDEX_PAGES_PER_PASS = 2       # per background cycle (~45s): about 3 requests/minute of the 45 shared
INDEX_MAX_ROUNDS = 14          # rounds kept in the index

_fetch_times: list[float] = []
_fetch_lock = threading.Lock()


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status(begin, end, now) -> str:
    begin, end = _aware(begin), _aware(end)
    if begin is not None and begin > now:
        return "upcoming"
    if end is not None and end < now:
        return "finished"
    return "live"


def _cached_lobby(w):
    return osirion_service._SET_LOBBY_CACHE.get((w.leaderboard_event_id, w.leaderboard_event_window_id))  # no network


def select_open_rounds(db: Session, windows: list) -> list:
    """Which of Osirion's windows count as open rounds of something we track (pure given the windows + the DB)."""
    mappings = db.query(OsirionTournamentMapping).all()
    tracked_keys = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in mappings}
    tracked_events = {m.osirion_event_id for m in mappings}
    planned, _ = osirion_service.plan_windows(db, windows, check_lobby=_cached_lobby)
    planned_keys = {(p.window.leaderboard_event_id, p.window.leaderboard_event_window_id) for p in planned}
    planned_events = {p.window.event_id for p in planned}
    paying_events = tracked_events | planned_events

    out = []
    for w in windows:
        key = (w.leaderboard_event_id, w.leaderboard_event_window_id)
        if not key[0] or not key[1] or key in tracked_keys or key in planned_keys:
            continue
        if w.is_zero_build or osirion_service.platform_restriction(w) or w.has_cash_payout:
            continue
        if not tracking_policy.reload_region_ok(w.regions, osirion_service.ALLOWED_TRACKING_REGIONS):
            continue
        role = tracking_policy.reload_family_role(w.classification_text)
        if role in (tracking_policy.ROLE_OPEN, tracking_policy.ROLE_QUALIFIER) or (role is None and w.event_id in paying_events):
            out.append(w)
    return out


def list_open_rounds(db: Session, force: bool = False) -> list[dict]:
    """The open rounds (newest first), cached for a few minutes. Osirion errors return an empty / cached list."""

    def compute() -> list[dict]:
        try:
            windows = osirion_service.list_available_windows(include_historic_data=True)
        except Exception:  # noqa: BLE001
            return []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=INDEX_DAYS)
        rows = []
        for w in select_open_rounds(db, windows):
            when = _aware(w.end_time or w.begin_time)
            if when is not None and when < cutoff:
                continue
            rows.append({
                "leaderboard_event_id": w.leaderboard_event_id,
                "leaderboard_event_window_id": w.leaderboard_event_window_id,
                "name": w.display_name,
                "event_id": w.event_id,
                "regions": list(w.regions),
                "start_time": w.begin_time,
                "end_time": w.end_time,
                "status": _status(w.begin_time, w.end_time, now),
            })
        rows.sort(key=lambda r: _aware(r["start_time"]) or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
        return rows

    if force:
        return compute()
    return cached_call(("open_rounds",), LIST_CACHE_SECONDS, compute)


class RoundNotFound(Exception):
    pass


class Busy(Exception):
    pass


def _find_round(db: Session, lb: str, lw: str) -> dict:
    for r in list_open_rounds(db):
        if r["leaderboard_event_id"] == lb and r["leaderboard_event_window_id"] == lw:
            return r
    raise RoundNotFound("That open round is not available.")


def _take_fetch_slot() -> None:
    now = time.monotonic()
    with _fetch_lock:
        while _fetch_times and now - _fetch_times[0] > 60:
            _fetch_times.pop(0)
        if len(_fetch_times) >= LIVE_FETCHES_PER_MINUTE:
            raise Busy("Lots of people are browsing open rounds right now. Try again in a few seconds.")
        _fetch_times.append(now)


def _names(entry: dict) -> list[str]:
    out = []
    for p in entry.get("players") or []:
        raw = p.get("username")
        out.append(osirion_service.clean_gamertag(raw) if raw else "(hidden)")
    return out or ["(unknown)"]


def get_page(db: Session, lb: str, lw: str, page: int) -> dict:
    """One page of an open round's leaderboard (cached; only rounds from the open-rounds list are allowed)."""
    rnd = _find_round(db, lb, lw)
    finished = rnd["status"] == "finished"
    page = max(0, min(int(page), 5000))

    def fetch() -> dict:
        _take_fetch_slot()
        try:
            lbd = osirion_client.get_leaderboard_page(lb, lw, page)
        except OsirionApiError as exc:
            raise Busy(f"Osirion is not answering right now ({exc}). Try again shortly.") from exc
        entries = lbd.get("entries") or []
        return {
            "page": page,
            "total_pages": int(lbd.get("totalPages") or 1),
            "entries": [
                {"rank": e.get("rank"), "points": e.get("pointsEarned", e.get("score")), "players": _names(e)} for e in entries
            ],
            "updated_at": lbd.get("updatedAt"),
        }

    data = cached_call(("open_round_page", lb, lw, page), FINISHED_PAGE_CACHE_SECONDS if finished else LIVE_PAGE_CACHE_SECONDS, fetch)
    return {"round": rnd, **data}


def search(db: Session, query: str, limit: int = 50) -> dict:
    """Players whose name contains `query`, across the indexed (finished) open rounds, best rank first."""
    q = (query or "").strip().lower()
    if len(q) < 2:
        return {"query": query, "results": [], "rounds_indexed": 0, "note": "Type at least 2 characters."}
    rows = (
        db.query(OpenRoundEntry, OpenRoundIndexState)
        .join(OpenRoundIndexState, OpenRoundIndexState.id == OpenRoundEntry.state_id)
        .filter(OpenRoundEntry.name_lc.contains(q))
        .order_by(OpenRoundEntry.rank.asc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    states = db.query(OpenRoundIndexState).all()
    return {
        "query": query,
        "results": [
            {
                "name": e.name, "rank": e.rank, "points": float(e.points) if e.points is not None else None,
                "round_name": s.display_name, "end_time": s.end_time,
                "leaderboard_event_id": s.leaderboard_event_id, "leaderboard_event_window_id": s.leaderboard_event_window_id,
            }
            for e, s in rows
        ],
        "rounds_indexed": sum(1 for s in states if s.is_complete or s.capped),
        "rounds_total": len(states),
        "note": f"Search covers finished rounds, top {INDEX_MAX_PAGES} pages of each. Live rounds: browse their pages.",
    }


def index_pass(db: Session) -> dict:
    """One throttled step of the background indexer: read up to INDEX_PAGES_PER_PASS pages of the newest unfinished-to-index
    finished round. Cheap no-op once everything is indexed. Never raises (best effort)."""
    result = {"pages": 0, "entries": 0, "rounds_done": 0}
    try:
        now = datetime.now(timezone.utc)
        finished = [r for r in list_open_rounds(db) if r["status"] == "finished"][:INDEX_MAX_ROUNDS]
        keep = {(r["leaderboard_event_id"], r["leaderboard_event_window_id"]) for r in finished}
        # Drop rounds that fell out of the window (and their rows).
        for s in db.query(OpenRoundIndexState).all():
            if (s.leaderboard_event_id, s.leaderboard_event_window_id) not in keep:
                db.query(OpenRoundEntry).filter(OpenRoundEntry.state_id == s.id).delete(synchronize_session=False)
                db.delete(s)
        db.commit()

        for r in finished:  # newest first
            state = (
                db.query(OpenRoundIndexState)
                .filter(OpenRoundIndexState.leaderboard_event_id == r["leaderboard_event_id"],
                        OpenRoundIndexState.leaderboard_event_window_id == r["leaderboard_event_window_id"])
                .one_or_none()
            )
            if state is None:
                state = OpenRoundIndexState(
                    leaderboard_event_id=r["leaderboard_event_id"], leaderboard_event_window_id=r["leaderboard_event_window_id"],
                    display_name=r["name"][:300], end_time=r["end_time"],
                )
                db.add(state)
                db.flush()
            if state.is_complete or state.capped:
                continue
            for _ in range(INDEX_PAGES_PER_PASS):
                if state.next_page >= INDEX_MAX_PAGES:
                    state.capped = True
                    break
                try:
                    lbd = osirion_client.get_leaderboard_page(state.leaderboard_event_id, state.leaderboard_event_window_id, state.next_page)
                except OsirionApiError:
                    break
                result["pages"] += 1
                entries = lbd.get("entries") or []
                state.total_pages = int(lbd.get("totalPages") or 1)
                seen: set[tuple] = set()
                for e in entries:
                    for name in _names(e):
                        key = (e.get("rank"), name.lower()[:80])
                        if e.get("rank") is None or name in ("(hidden)", "(unknown)") or key in seen:
                            continue
                        seen.add(key)
                        db.add(OpenRoundEntry(state_id=state.id, rank=int(e["rank"]), name=name[:80], name_lc=name.lower()[:80],
                                              points=e.get("pointsEarned", e.get("score"))))
                        result["entries"] += 1
                        state.entries_indexed += 1
                state.next_page += 1
                state.last_synced_at = now
                if state.next_page >= state.total_pages:
                    state.is_complete = True
                    result["rounds_done"] += 1
                    break
                if state.next_page >= INDEX_MAX_PAGES:
                    state.capped = True
                    break
            db.commit()
            break  # one round per pass keeps the request rate low
    except Exception:  # noqa: BLE001 -- indexing must never disturb the sync loop
        db.rollback()
        logger.exception("open-round index pass failed")
    return result
