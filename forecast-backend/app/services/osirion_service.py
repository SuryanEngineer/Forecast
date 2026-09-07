"""
Turns Osirion's raw tournament/leaderboard data
(app/integrations/osirion_client.py) into this app's own Tournament /
PlacementResult rows, using the exact same adapter interface
tournament_service.py already anticipated for an automated importer (see
that module's docstring): upsert_placement_result + finalize_tournament,
called the same way the admin API calls them -- this module never
touches PlacementResult/Tournament rows directly itself.

Three admin-facing operations (see app/api/v1/admin.py):
1. `list_available_windows` -- browse what Osirion currently has, to pick
   one to track.
2. `track_tournament` -- record which internal Tournament corresponds to
   which Osirion leaderboard (creates the Tournament too, in one call).
3. `sync_tournament` / `sync_all_tracked` -- pull the latest standings for
   a tracked tournament and (once its window has ended) finalize it. Also
   runs automatically -- see app/main.py's `_osirion_sync_loop`, gated on
   settings.OSIRION_SYNC_ENABLED.

Player matching (see `_match_player`): Osirion identifies players by an
opaque Epic `accountId` plus a `username` that may be null (privacy) and
can change over time. We match on `username` case-insensitively against
Player.gamertag the FIRST time we see a given accountId, then remember
that mapping (OsirionPlayerMapping) so every later sync is a fast,
name-change-proof lookup by accountId. An unmatched entry (no existing
mapping AND no username match) is skipped, not guessed at -- see
SyncResult.unmatched_usernames for how an admin finds out this happened.

Note Osirion's leaderboard entries are per-TEAM, not per-player (`players`
is an array -- duos/squads share one `rank`), so a single entry can
produce more than one PlacementResult, all at the same placement.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.integrations import osirion_client
from app.integrations.osirion_client import OsirionApiError
from app.models.osirion import OsirionPlayerMapping, OsirionTournamentMapping
from app.models.player import Player
from app.models.tournament import ResultSource, Tournament, TournamentStatus, TournamentType
from app.services import tournament_service

logger = logging.getLogger("forecast.osirion")


@dataclass
class AvailableWindow:
    """One trackable (tournament, round/window, score-location) combination
    -- i.e. everything an admin needs to call track_tournament, flattened
    out of Osirion's nested eventWindows[].scoreLocations[] shape. The
    leaderboard_event_id/leaderboard_event_window_id pair (NOT event_id/
    event_window_id) is what actually gets queried for results."""

    event_id: str
    event_window_id: str
    round: int
    leaderboard_event_id: str
    leaderboard_event_window_id: str
    is_main: bool
    begin_time: datetime | None
    end_time: datetime | None
    display_name: str
    regions: list[str]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _display_name(tournament: dict) -> str:
    display = tournament.get("displayData") or {}
    return (
        display.get("longFormatTitle")
        or " ".join(filter(None, [display.get("titleLine1"), display.get("titleLine2")])).strip()
        or tournament.get("eventGroup")
        or tournament.get("eventId", "Unknown tournament")
    )


def list_available_windows(region: str | None = None, include_historic_data: bool = False) -> list[AvailableWindow]:
    """Flattens Osirion's /v1/tournaments response into one row per
    trackable window, for an admin picker UI. Prefers each window's
    isMain-flagged score location; falls back to the first one if none is
    flagged main."""
    tournaments = osirion_client.list_tournaments(region=region, include_historic_data=include_historic_data)
    windows: list[AvailableWindow] = []

    for tournament in tournaments:
        name = _display_name(tournament)
        event_id = tournament.get("eventId", "")
        regions = tournament.get("regions", [])

        for event_window in tournament.get("eventWindows", []):
            score_locations = event_window.get("scoreLocations", [])
            if not score_locations:
                continue
            chosen = next((sl for sl in score_locations if sl.get("isMain")), score_locations[0])
            round_num = event_window.get("round", 0)

            windows.append(
                AvailableWindow(
                    event_id=event_id,
                    event_window_id=event_window.get("eventWindowId", ""),
                    round=round_num,
                    leaderboard_event_id=chosen.get("leaderboardEventId", ""),
                    leaderboard_event_window_id=chosen.get("leaderboardEventWindowId", ""),
                    is_main=bool(chosen.get("isMain")),
                    begin_time=_parse_iso(event_window.get("beginTime")),
                    end_time=_parse_iso(event_window.get("endTime")),
                    display_name=f"{name} — Round {round_num}",
                    regions=regions,
                )
            )

    return windows


def track_tournament(
    db: Session,
    *,
    name: str,
    tournament_type: TournamentType,
    region: str | None,
    window: AvailableWindow,
    created_by_admin_id: uuid.UUID | None,
) -> OsirionTournamentMapping:
    """Creates a new internal Tournament (result_source=API_IMPORT) plus
    its OsirionTournamentMapping, in one call. `name`/`tournament_type`
    are chosen by the admin -- Osirion has no typed FNCS-vs-Cash-Cup field
    to trust (see this module's docstring) -- everything else comes from
    the picked `window` (see list_available_windows)."""
    tournament = tournament_service.create_tournament(
        db,
        name=name,
        tournament_type=tournament_type,
        region=region,
        start_time=window.begin_time,
        end_time=window.end_time,
        created_by_admin_id=created_by_admin_id,
        result_source=ResultSource.API_IMPORT,
    )

    mapping = OsirionTournamentMapping(
        id=uuid.uuid4(),
        tournament_id=tournament.id,
        osirion_event_id=window.event_id,
        osirion_event_window_id=window.event_window_id,
        leaderboard_event_id=window.leaderboard_event_id,
        leaderboard_event_window_id=window.leaderboard_event_window_id,
        osirion_display_name=window.display_name,
        window_begin_time=window.begin_time,
        window_end_time=window.end_time,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def _match_player(db: Session, osirion_player: dict) -> Player | None:
    account_id = osirion_player.get("accountId")
    username = osirion_player.get("username")

    if account_id:
        existing = (
            db.query(OsirionPlayerMapping)
            .filter(OsirionPlayerMapping.osirion_account_id == account_id)
            .one_or_none()
        )
        if existing is not None:
            return db.get(Player, existing.player_id)

    if not username:
        return None

    # Escape SQL LIKE wildcards (% and _) that could theoretically appear
    # in a Fortnite display name -- ilike() would otherwise treat them as
    # pattern characters instead of literal ones.
    escaped_username = username.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    player = db.query(Player).filter(Player.gamertag.ilike(escaped_username, escape="\\")).one_or_none()
    if player is None:
        return None

    if account_id:
        db.add(
            OsirionPlayerMapping(
                id=uuid.uuid4(), osirion_account_id=account_id, osirion_username=username, player_id=player.id
            )
        )
        db.flush()

    return player


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


@dataclass
class SyncResult:
    tournament_id: uuid.UUID
    entries_seen: int = 0
    matched: int = 0
    unmatched_usernames: list[str] = field(default_factory=list)
    finalized: bool = False
    error: str | None = None


def sync_tournament(db: Session, mapping: OsirionTournamentMapping) -> SyncResult:
    result = SyncResult(tournament_id=mapping.tournament_id)
    tournament = db.get(Tournament, mapping.tournament_id)
    if tournament is None or tournament.status == TournamentStatus.FINALIZED:
        return result

    try:
        page = 0
        total_pages = 1
        while page < total_pages:
            leaderboard = osirion_client.get_leaderboard_page(
                mapping.leaderboard_event_id, mapping.leaderboard_event_window_id, page=page
            )
            total_pages = leaderboard.get("totalPages") or 1
            entries = leaderboard.get("entries", [])

            for entry in entries:
                rank = entry.get("rank")
                if not rank or rank <= 0:
                    continue
                points = _to_decimal(entry.get("pointsEarned"))
                for osirion_player in entry.get("players", []):
                    result.entries_seen += 1
                    player = _match_player(db, osirion_player)
                    if player is None:
                        if osirion_player.get("username"):
                            result.unmatched_usernames.append(osirion_player["username"])
                        continue
                    tournament_service.upsert_placement_result(
                        db,
                        tournament_id=tournament.id,
                        player_id=player.id,
                        placement=rank,
                        points=points,
                    )
                    result.matched += 1

            page += 1

        mapping.last_synced_at = datetime.now(timezone.utc)
        db.commit()
    except OsirionApiError as exc:
        db.rollback()
        result.error = str(exc)
        logger.warning("Osirion sync failed for tournament %s: %s", tournament.id, exc)
        return result
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment below
        # Anything else (malformed data from Osirion tripping up
        # _match_player, an unexpected DB error, etc.) must not escape this
        # function. This is called both from a loop over EVERY tracked
        # tournament (sync_all_tracked) and from a single-tournament admin
        # endpoint (POST .../sync-now) -- letting one bad tournament's
        # exception propagate would either abort every other tournament's
        # sync for this pass (list comprehension short-circuits) or surface
        # as a raw 500 instead of a clean error response. Recorded on the
        # result and logged with a full traceback instead; the next sync
        # pass (or another manual sync-now click) tries again.
        db.rollback()
        result.error = f"unexpected error: {exc}"
        logger.exception("Osirion sync raised an unexpected error for tournament %s", tournament.id)
        return result

    window_end_time = mapping.window_end_time
    if window_end_time is not None and window_end_time.tzinfo is None:
        # SQLite (demo mode) drops tzinfo on DateTime(timezone=True)
        # columns on read-back -- see password_reset_service.confirm_reset
        # for the same fix and why a naive value here is always UTC, never
        # local time. No-op on Postgres, where this is already tz-aware.
        window_end_time = window_end_time.replace(tzinfo=timezone.utc)

    if (
        window_end_time is not None
        and window_end_time < datetime.now(timezone.utc)
        and result.matched > 0
    ):
        try:
            tournament_service.finalize_tournament(db, tournament.id)
            result.finalized = True
        except ValueError as exc:
            # e.g. every entry this pass was unmatched, so there are
            # still zero placement results -- leave it for the next sync
            # rather than crashing the whole loop.
            logger.warning("Could not finalize tournament %s yet: %s", tournament.id, exc)
        except Exception as exc:  # noqa: BLE001 -- same reasoning as the sync try/except above
            # A finalize-time failure (e.g. a DB error while creating
            # payouts) must not propagate out of sync_tournament either --
            # the sync itself already succeeded and committed above; only
            # the finalize step failed. Leave it for the next sync attempt.
            db.rollback()
            result.error = f"sync succeeded but finalize failed: {exc}"
            logger.exception("Finalizing tournament %s failed unexpectedly", tournament.id)

    return result


def sync_all_tracked(db: Session) -> list[SyncResult]:
    mappings = (
        db.query(OsirionTournamentMapping)
        .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
        .filter(Tournament.status != TournamentStatus.FINALIZED)
        .all()
    )

    results: list[SyncResult] = []
    for mapping in mappings:
        try:
            results.append(sync_tournament(db, mapping))
        except Exception as exc:  # noqa: BLE001 -- defense in depth
            # sync_tournament already catches everything it can from
            # within its own try block, but this belt-and-suspenders catch
            # ensures that even a failure OUTSIDE that block (e.g. the
            # `db.get(Tournament, ...)` call at its very top) can't take
            # down every other tournament's sync in this same pass.
            db.rollback()
            logger.exception("sync_tournament itself raised for mapping %s", mapping.id)
            results.append(SyncResult(tournament_id=mapping.tournament_id, error=f"unexpected error: {exc}"))
    return results
