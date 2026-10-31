"""
"Missed the event" signal: a pro who normally plays a region's big events but is NOT in the field of one is a mildly
bad sign (they failed to qualify, dropped out of the circuit, or sat it out), so their stock should slip a little.

A player counts as having missed a tournament when ALL of these hold:
  * the tournament is a qualifying-style event (FNCS qualifier / finals, major, global championship -- weekly cash cups
    are skipped: lots of good players simply do not enter every one) and is already over,
  * it belongs to the player's own region (cross-region events are ignored),
  * the player played at least one event of that same type and region in the previous MISSED_LOOKBACK_DAYS (so
    someone who never competes in that circuit is not "missing" anything),
  * the player has no placement in it, and it had a real field (>= MIN_FIELD placements, so half-synced events do not
    count anybody as absent).

The drop is small (MISSED_PENALTY, as a log-price move) and fades with a half-life of roughly two weeks
(MISSED_DECAY_DAYS). Shared by the live bots (bot_trading_service) and the 2026 history simulation
(scripts/simulate_price_history.py) so the past and the present follow one rule.
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.tournament import PlacementResult, Tournament, TournamentStatus, TournamentType

MISSED_PENALTY: dict[TournamentType, float] = {
    TournamentType.FNCS_QUALIFIER: 0.02,
    TournamentType.FNCS_FINALS: 0.04,
    TournamentType.MAJOR: 0.03,
    TournamentType.GLOBAL_CHAMPIONSHIP: 0.03,
}
MISSED_LOOKBACK_DAYS = 400
MISSED_DECAY_DAYS = 20.0
MIN_FIELD = 20


def region_key(region: str | None) -> str | None:
    """Upper-cased single region, or None for a missing / cross-region ("MULTI") value."""
    if not region:
        return None
    key = region.strip().upper()
    return None if key in ("", "MULTI") else key


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def fill_regions(db: Session, player_regions: dict[uuid.UUID, str | None]) -> dict[uuid.UUID, str | None]:
    """Many players have no Player.region (Osirion does not always give one). For those, use the region of the
    single-region tournaments they have actually played in -- the most common one wins."""
    out = dict(player_regions)
    missing = [pid for pid, r in out.items() if region_key(r) is None]
    if not missing:
        return out
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for pid, region in (
        db.query(PlacementResult.player_id, Tournament.region)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(PlacementResult.player_id.in_(missing), Tournament.region.isnot(None))
        .all()
    ):
        rk = region_key(region)
        if rk is not None:
            counts[pid][rk] += 1
    for pid, c in counts.items():
        out[pid] = max(c.items(), key=lambda kv: kv[1])[0]
    return out


def missed_events(
    db: Session, player_regions: dict[uuid.UUID, str | None], since: datetime, now: datetime | None = None
) -> list[tuple[uuid.UUID, datetime, float]]:
    """[(player_id, event_time, penalty)] for every missed event whose start is on/after `since` and that is already
    over. `event_time` is the tournament's end (start + 1 day when the end is unknown)."""
    now = now or datetime.now(timezone.utc)
    player_regions = fill_regions(db, player_regions)
    types = list(MISSED_PENALTY.keys())
    rows = (
        db.query(Tournament.id, Tournament.tournament_type, Tournament.region, Tournament.start_time, Tournament.end_time, Tournament.status)
        .filter(Tournament.tournament_type.in_(types), Tournament.start_time.isnot(None), Tournament.start_time >= since)
        .all()
    )
    events = []
    for tid, ttype, region, start, end, status in rows:
        rk = region_key(region)
        if rk is None:
            continue
        start = _aware(start)
        when = _aware(end) if end is not None else start + timedelta(days=1)
        if when > now and status != TournamentStatus.FINALIZED:
            continue
        events.append((tid, ttype, rk, start, min(when, now)))
    if not events:
        return []

    ids = [e[0] for e in events]
    field = {tid: n for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(ids)).group_by(PlacementResult.tournament_id).all()}
    played: dict[uuid.UUID, set] = defaultdict(set)
    for tid, pid in db.query(PlacementResult.tournament_id, PlacementResult.player_id).filter(PlacementResult.tournament_id.in_(ids)).all():
        played[tid].add(pid)

    # When each player played each (type, region) circuit, to check "was active in this circuit recently".
    circuit: dict[tuple, list[datetime]] = defaultdict(list)
    wanted = set(player_regions)
    for pid, ttype, region, start in (
        db.query(PlacementResult.player_id, Tournament.tournament_type, Tournament.region, Tournament.start_time)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(Tournament.tournament_type.in_(types), Tournament.start_time.isnot(None),
                Tournament.start_time >= since - timedelta(days=MISSED_LOOKBACK_DAYS))
        .all()
    ):
        rk = region_key(region)
        if rk is not None and pid in wanted:
            circuit[(pid, ttype, rk)].append(_aware(start))

    by_region: dict[str, list[uuid.UUID]] = defaultdict(list)
    for pid, region in player_regions.items():
        rk = region_key(region)
        if rk is not None:
            by_region[rk].append(pid)

    out: list[tuple[uuid.UUID, datetime, float]] = []
    for tid, ttype, rk, start, when in events:
        if field.get(tid, 0) < MIN_FIELD:
            continue
        pen = MISSED_PENALTY[ttype]
        horizon = start - timedelta(days=MISSED_LOOKBACK_DAYS)
        for pid in by_region.get(rk, ()):
            if pid in played[tid]:
                continue
            if any(horizon <= t < start for t in circuit.get((pid, ttype, rk), ())):
                out.append((pid, when, pen))
    return out


def decayed_penalty(events: list[tuple[datetime, float]], at: datetime) -> float:
    """Total log-price penalty (a positive number) from missed events at or before `at`, each fading over time."""
    total = 0.0
    for when, pen in events:
        if when <= at:
            total += pen * math.exp(-((at - when).total_seconds() / 86400.0) / MISSED_DECAY_DAYS)
    return total
