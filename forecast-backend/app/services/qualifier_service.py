"""
Fetches the EARLIER ROUNDS (qualifiers / heats / day-1 etc.) of a tracked Finals event from Osirion and stores how our
roster players did in them -- see app/models/qualifier.py.

How the rounds are found
------------------------
Osirion lists every round of an event as its own window under the same `eventId`. The cash-paying window is the one we
track as a Tournament (osirion_service.auto_track_new_tournaments); every OTHER window of that event that starts before it
and pays no cash (only advancement tokens) is an earlier round. Rounds are ordered by start time (Osirion's own `round`
counter is unreliable). Each round's payout table also says which rank earns the advancement token, which we keep as
`advance_cutoff`.

Guard rails (this is the code path that once grew the roster to 89,702 players -- do not loosen these)
------------------------------------------------------------------------------------------------------
  * NEVER creates a Player: only people already on the roster (matched by saved account id, then by name/alias) are stored.
  * Ended rounds only (a live round's standings still move); a finished round never changes, so it is read once.
  * Page budget per sync pass (settings.QUALIFIER_PAGES_PER_PASS) and a per-round page cap
    (settings.QUALIFIER_MAX_PAGES_PER_WINDOW), with a resumable cursor, so it can't starve the Finals sync or hammer Osirion's
    shared rate limit. A round stopped at the cap is flagged `capped`: nobody is inferred "eliminated" from it.
  * Errors are per-round and never raise into the sync loop.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.qualifier_math import qual_score  # noqa: F401  (re-exported)
from app.integrations import osirion_client
from app.integrations.osirion_client import OsirionApiError
from app.models.osirion import OsirionPlayerMapping, OsirionTournamentMapping, PlayerAlias
from app.models.player import Player
from app.models.qualifier import QualifierResult, QualifierWindow
from app.models.tournament import Tournament, TournamentStatus, TournamentType
from app.services import osirion_service
from app.services.player_identity import skeleton

logger = logging.getLogger("forecast.osirion")

_WINDOW_CACHE_TTL = 30 * 60
_window_cache: tuple[float, list] | None = None
_ROUND_ENDED_GRACE = timedelta(minutes=5)


def parse_advance_cutoff(raw_event_window: dict, leaderboard_window_id: str) -> int | None:
    """The worst rank that still earns an advancement token ("standard" token reward in a rank payout table), taken from
    the score location for this leaderboard. Ignores deny/lock bookkeeping tokens. None when no such table exists."""
    best: int | None = None
    for sl in (raw_event_window or {}).get("scoreLocations") or []:
        if sl.get("leaderboardEventWindowId") != leaderboard_window_id:
            continue
        for table in sl.get("payoutTables") or []:
            if (table.get("scoringType") or "rank") != "rank":
                continue
            for rank_entry in table.get("ranks") or []:
                threshold = rank_entry.get("threshold")
                if not isinstance(threshold, int) or threshold <= 0:
                    continue
                for payout in rank_entry.get("payouts") or []:
                    if (payout.get("rewardType") or "").lower() != "token":
                        continue
                    if (payout.get("rewardMode") or "standard").lower() != "standard":
                        continue
                    token = str(payout.get("value") or "").lower()
                    if "deny" in token or "regionlock" in token:
                        continue
                    if (payout.get("quantity") or 0) <= 0:
                        continue
                    best = threshold if best is None else max(best, threshold)
    return best


def _all_windows(force: bool = False) -> list:
    """Every Osirion window (NAC + EU, including recent history), cached for 30 minutes."""
    global _window_cache
    now = time.monotonic()
    if not force and _window_cache is not None and now - _window_cache[0] < _WINDOW_CACHE_TTL:
        return _window_cache[1]
    try:
        windows = osirion_service.list_available_windows(None, include_historic_data=True)
    except OsirionApiError as exc:
        logger.warning("Qualifier sync: could not list Osirion windows (%s)", exc)
        return _window_cache[1] if _window_cache else []
    _window_cache = (now, windows)
    return windows


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _types() -> set[TournamentType]:
    out: set[TournamentType] = set()
    for raw in (settings.QUALIFIER_TOURNAMENT_TYPES or "").split(","):
        raw = raw.strip().lower()
        for t in TournamentType:
            if t.value == raw:
                out.add(t)
    return out


class _Roster:
    """In-memory view of the active roster so a 50,000-entry field costs almost no queries: anyone not already known by
    account id, gamertag or alias is skipped without touching the database."""

    def __init__(self, db: Session) -> None:
        active = db.query(Player.id, Player.gamertag).filter(Player.is_active.is_(True)).all()
        self.active_ids = {pid for pid, _ in active}
        self.by_tag = {(g or "").lower(): pid for pid, g in active}
        self.by_account: dict[str, uuid.UUID] = {
            acct: pid
            for acct, pid in db.query(OsirionPlayerMapping.osirion_account_id, OsirionPlayerMapping.player_id)
            .join(Player, Player.id == OsirionPlayerMapping.player_id).filter(Player.is_active.is_(True)).all()
        }
        self.by_alias = {k: pid for k, pid in db.query(PlayerAlias.alias_key, PlayerAlias.player_id).all() if pid in self.active_ids}

    def match(self, db: Session, op: dict) -> uuid.UUID | None:
        acct = op.get("accountId")
        if acct and acct in self.by_account:
            return self.by_account[acct]
        username = op.get("username")
        if not username:
            return None
        if (
            osirion_service.clean_gamertag(username).lower() not in self.by_tag
            and skeleton(username) not in self.by_alias
        ):
            return None
        player = osirion_service._match_player(db, op, create_missing=False)  # saves the account mapping for next time
        if player is None or player.id not in self.active_ids:
            return None
        if acct:
            self.by_account[acct] = player.id
        return player.id


# ---- discovery --------------------------------------------------------------------------------------------------------


def discover_round_windows(db: Session, mapping: OsirionTournamentMapping, windows: list) -> list[QualifierWindow]:
    """Creates/updates QualifierWindow rows for every earlier round of this Finals' event."""
    final_begin = _aware(mapping.window_begin_time)
    if final_begin is None:
        return []
    siblings = [
        w for w in windows
        if w.event_id == mapping.osirion_event_id
        and not w.has_cash_payout
        and not w.is_zero_build
        and w.leaderboard_event_window_id
        and w.leaderboard_event_window_id != mapping.leaderboard_event_window_id
        and _aware(w.begin_time) is not None
        and _aware(w.begin_time) < final_begin
    ]
    # One row per distinct leaderboard (a window can be listed under both regions).
    unique: dict[tuple, object] = {}
    for w in siblings:
        unique.setdefault((w.leaderboard_event_id, w.leaderboard_event_window_id), w)
    ordered = sorted(unique.values(), key=lambda w: _aware(w.begin_time))

    existing = {
        (r.leaderboard_event_id, r.leaderboard_event_window_id): r
        for r in db.query(QualifierWindow).filter(QualifierWindow.tournament_id == mapping.tournament_id).all()
    }
    out: list[QualifierWindow] = []
    for idx, w in enumerate(ordered, start=1):
        key = (w.leaderboard_event_id, w.leaderboard_event_window_id)
        row = existing.get(key)
        cutoff = parse_advance_cutoff(w.raw_event_window, w.leaderboard_event_window_id)
        if row is None:
            row = QualifierWindow(
                id=uuid.uuid4(), tournament_id=mapping.tournament_id, osirion_event_id=w.event_id,
                event_window_id=w.event_window_id, leaderboard_event_id=w.leaderboard_event_id,
                leaderboard_event_window_id=w.leaderboard_event_window_id, display_name=w.display_name,
                stage_index=idx, begin_time=w.begin_time, end_time=w.end_time, advance_cutoff=cutoff,
            )
            db.add(row)
        else:
            row.stage_index, row.begin_time, row.end_time = idx, w.begin_time, w.end_time
            if cutoff is not None:
                row.advance_cutoff = cutoff
        out.append(row)
    db.flush()
    return out


# ---- fetching ---------------------------------------------------------------------------------------------------------


@dataclass
class QualifierSyncResult:
    windows_known: int = 0
    pages_fetched: int = 0
    results_stored: int = 0
    windows_completed: int = 0
    errors: list[str] = field(default_factory=list)


def _store_entry(db: Session, window: QualifierWindow, roster: _Roster, entry: dict) -> int:
    rank = entry.get("rank")
    if not isinstance(rank, int) or rank <= 0:
        return 0
    players = entry.get("players") or []
    matched: list[uuid.UUID] = []
    for op in players:
        pid = roster.match(db, op)
        if pid is not None and pid not in matched:
            matched.append(pid)
    if not matched:
        return 0
    try:
        pct = Decimal(str(entry["percentile"])) if entry.get("percentile") is not None else None
    except Exception:  # noqa: BLE001
        pct = None
    try:
        points = Decimal(str(entry["pointsEarned"])) if entry.get("pointsEarned") is not None else None
    except Exception:  # noqa: BLE001
        points = None
    stored = 0
    for pid in matched:
        exists = db.query(QualifierResult.id).filter(QualifierResult.window_id == window.id, QualifierResult.player_id == pid).first()
        if exists is not None:
            continue
        db.add(QualifierResult(
            id=uuid.uuid4(), window_id=window.id, tournament_id=window.tournament_id, player_id=pid, rank=rank,
            percentile=pct, points=points, team_id=entry.get("teamId"), team_size=max(1, len(players)),
            teammate_player_ids=[str(t) for t in matched if t != pid],
        ))
        stored += 1
    return stored


def _walk_window(db: Session, window: QualifierWindow, roster: _Roster, budget: int, result: QualifierSyncResult) -> int:
    """Reads up to `budget` pages of one round; returns pages used."""
    used = 0
    cap = settings.QUALIFIER_MAX_PAGES_PER_WINDOW
    while used < budget and not window.is_complete:
        page = window.next_page
        try:
            lb = osirion_client.get_leaderboard_page(window.leaderboard_event_id, window.leaderboard_event_window_id, page=page)
        except OsirionApiError as exc:
            db.rollback()
            result.errors.append(f"{window.leaderboard_event_window_id}: {exc}")
            break
        used += 1
        result.pages_fetched += 1
        entries = lb.get("entries") or []
        total_pages = lb.get("totalPages") or 1
        window.total_pages = total_pages
        if page == 0 and entries:
            window.field_estimate = total_pages * len(entries)
        for entry in entries:
            window.entries_seen += len(entry.get("players") or [])
            n = _store_entry(db, window, roster, entry)
            window.matched += n
            result.results_stored += n
        window.next_page = page + 1
        window.last_synced_at = datetime.now(timezone.utc)
        if window.next_page >= total_pages or not entries:
            window.is_complete = True
        elif window.next_page >= cap:
            window.is_complete = True
            window.capped = True
        if window.is_complete:
            result.windows_completed += 1
        db.commit()
    return used


def sync_qualifiers(db: Session, max_pages: int | None = None, only_types: set[TournamentType] | None = None) -> QualifierSyncResult:
    """One rate-budgeted pass: discover the rounds of every relevant event, then read ended rounds that are not complete
    yet (upcoming Finals first). Safe to call every sync loop; does nothing when everything is up to date."""
    result = QualifierSyncResult()
    if not settings.QUALIFIER_SYNC_ENABLED:
        return result
    types = only_types or _types()
    if not types:
        return result
    budget = max_pages if max_pages is not None else settings.QUALIFIER_PAGES_PER_PASS

    try:
        base = (
            db.query(OsirionTournamentMapping, Tournament)
            .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
            .filter(Tournament.tournament_type.in_(list(types)))
        )
        live = [(m, t) for m, t in base.filter(Tournament.status != TournamentStatus.FINALIZED).all()]
        recent_done = (
            base.filter(Tournament.status == TournamentStatus.FINALIZED)
            .order_by(OsirionTournamentMapping.window_begin_time.desc().nullslast())
            .limit(max(0, settings.QUALIFIER_HISTORY_EVENTS)).all()
        )
        all_windows = _all_windows()
        known: list[QualifierWindow] = []
        if all_windows:
            for m, _t in live + list(recent_done):
                known.extend(discover_round_windows(db, m, all_windows))
            db.commit()
        result.windows_known = len(known)

        now = datetime.now(timezone.utc)
        live_ids = {t.id for _m, t in live}
        pending = [
            w for w in known
            if not w.is_complete and _aware(w.end_time) is not None and _aware(w.end_time) + _ROUND_ENDED_GRACE <= now
        ]
        pending.sort(key=lambda w: (w.tournament_id not in live_ids, -(_aware(w.end_time) or now).timestamp()))
        if not pending or budget <= 0:
            return result
        roster = _Roster(db)
        for w in pending:
            if budget <= 0:
                break
            budget -= _walk_window(db, w, roster, budget, result)
    except Exception as exc:  # noqa: BLE001 -- never break the Osirion sync loop
        db.rollback()
        logger.exception("Qualifier sync failed")
        result.errors.append(f"unexpected: {exc}")
    return result
