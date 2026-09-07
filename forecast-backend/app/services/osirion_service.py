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
4. `auto_track_new_tournaments` -- runs automatically on the same loop,
   just before the sync pass above (gated on
   settings.OSIRION_AUTO_TRACK_ENABLED): classifies every currently-open
   Osirion window via tournament_classification_service and calls
   `track_tournament` for anything that matches a wanted tier, so an admin
   no longer has to manually browse/pick windows for the tournaments this
   covers. Manual tracking via the three functions above still works for
   anything auto-tracking doesn't recognize.

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
from app.models.tournament import ResultSource, Tournament, TournamentEntrant, TournamentStatus, TournamentType
from app.services import player_service, tournament_classification_service, tournament_service

logger = logging.getLogger("forecast.osirion")


@dataclass
class AvailableWindow:
    """One trackable (tournament, round/window, score-location) combination
    -- i.e. everything an admin needs to call track_tournament, flattened
    out of Osirion's nested eventWindows[].scoreLocations[] shape. The
    leaderboard_event_id/leaderboard_event_window_id pair (NOT event_id/
    event_window_id) is what actually gets queried for results.

    `round` is Osirion's own eventWindows[].round field -- it turned out to
    be unreliable in practice (observed stuck at 0 on real data for some
    tournament families) so it's kept here for admin-display/debugging
    only; nothing in auto_track_new_tournaments trusts it any more to mean
    "which round is the real Finals" -- see has_cash_payout/top_cash_amount
    below for the signal that actually works.

    `has_cash_payout`/`top_cash_amount` are derived from this window's
    chosen score location's `payoutTables`: a heat/qualifier window pays
    out only advancement tokens (rewardType "token"), while the genuine
    payout round pays real money (rewardType e.g. "ecomm"). A window with
    has_cash_payout=False is a heat, not something that should ever be
    auto-tracked as a real dividend-paying Tournament.

    `is_zero_build` flags a "ZB"/"No Build" variant tournament (detected
    via Osirion's naming convention -- there's no dedicated boolean field
    for this), which is never auto-tracked."""

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
    has_cash_payout: bool = False
    top_cash_amount: Decimal = Decimal("0")
    is_zero_build: bool = False
    event_group: str = ""

    @property
    def classification_text(self) -> str:
        """What tournament_classification_service.classify() actually
        scans. Osirion's human-readable title alone isn't always enough --
        e.g. a real EWC LAN's title is literally "Reload Elite Series
        Championship" with no "EWC"/"global"/etc in it at all; the "EWC"
        branding only shows up in eventGroup ("EWC"). Combining both means
        a rule can match on whichever one actually carries the signal."""
        return f"{self.display_name} {self.event_group} {self.event_id}"


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


def _cash_payout_info(score_location: dict) -> tuple[bool, Decimal]:
    """Scans one score location's payoutTables for any reward that isn't
    a mere advancement token. Returns (has_real_cash_payout,
    top_rank1-ish_cash_amount) -- see AvailableWindow's docstring."""
    has_cash = False
    top_amount = Decimal("0")
    for table in score_location.get("payoutTables") or []:
        for rank_entry in table.get("ranks") or []:
            for payout in rank_entry.get("payouts") or []:
                reward_type = (payout.get("rewardType") or "").strip().lower()
                if reward_type == "token" or not reward_type:
                    continue
                has_cash = True
                amount = _to_decimal(payout.get("quantity"))
                if amount is not None and amount > top_amount:
                    top_amount = amount
    return has_cash, top_amount


_ZERO_BUILD_MARKERS = ("zb", "no build", "nobuild", "no-build")


def _is_zero_build(tournament: dict, event_window: dict, display_name_str: str) -> bool:
    """Zero Build (ZB) tournaments are never auto-tracked. Osirion has no
    dedicated boolean for this -- it's encoded as a naming convention
    across eventGroup/eventId (e.g. 'S41_CashCup_DuosZB'), the
    human-readable title (e.g. 'Console Solo Victory Cup (ZB)'), and each
    window's playlistId (e.g. 'Playlist_ShowdownTournament_NoBuildBR_Duos')."""
    haystack = " ".join(
        filter(
            None,
            [
                tournament.get("eventGroup"),
                tournament.get("eventId"),
                display_name_str,
                event_window.get("playlistId"),
            ],
        )
    ).lower()
    return any(marker in haystack for marker in _ZERO_BUILD_MARKERS)


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
            has_cash_payout, top_cash_amount = _cash_payout_info(chosen)
            is_zero_build = _is_zero_build(tournament, event_window, name)

            begin_time = _parse_iso(event_window.get("beginTime"))
            # Osirion's `round` counter is unreliable (see AvailableWindow's
            # docstring) -- disambiguate recurring tournaments (e.g. a
            # biweekly Cash Cup) by date instead of a meaningless round
            # number, so names never show something like "Round 0" twice
            # for two genuinely different editions, or a stale "Round 4"
            # for what's actually the very first edition.
            suffix = begin_time.strftime("%b %d, %Y") if begin_time else (event_window.get("eventWindowId") or "TBD")

            windows.append(
                AvailableWindow(
                    event_id=event_id,
                    event_window_id=event_window.get("eventWindowId", ""),
                    round=round_num,
                    leaderboard_event_id=chosen.get("leaderboardEventId", ""),
                    leaderboard_event_window_id=chosen.get("leaderboardEventWindowId", ""),
                    is_main=bool(chosen.get("isMain")),
                    begin_time=begin_time,
                    end_time=_parse_iso(event_window.get("endTime")),
                    display_name=f"{name} — {suffix}",
                    regions=regions,
                    has_cash_payout=has_cash_payout,
                    top_cash_amount=top_cash_amount,
                    is_zero_build=is_zero_build,
                    event_group=tournament.get("eventGroup") or "",
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
        # Nothing to display and nothing to match on -- genuinely can't
        # create a placeholder without at least a gamertag to show.
        return None

    # Escape SQL LIKE wildcards (% and _) that could theoretically appear
    # in a Fortnite display name -- ilike() would otherwise treat them as
    # pattern characters instead of literal ones.
    escaped_username = username.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    player = db.query(Player).filter(Player.gamertag.ilike(escaped_username, escape="\\")).one_or_none()

    if player is None:
        # No existing Player has this gamertag -- rather than silently
        # dropping this competitor (which produces gaps in the
        # leaderboard, e.g. "50th place" then "52nd place"), auto-create
        # a placeholder with ZERO total_shares_outstanding. That one value
        # flows through every existing formula with no special-casing
        # needed elsewhere:
        #   - execute_quick_order's max_synthetic_quantity cap on the
        #     House's real inventory is 0 for this player, so a BUY quick
        #     order cleanly raises NoLiquidityError instead of a
        #     nonsensical fill; a SELL requires shares nobody can hold.
        #   - dividend_service.create_payout_for_placement snapshots
        #     shares_outstanding_snapshot=0 on the payout, and
        #     compute_dividend_distribution's explicit
        #     `shares_outstanding <= 0` guard returns a clean $0.00/no
        #     holders result instead of silently paying the House 100% of
        #     the pool (the House still holds a Position row for this
        #     player, same as any new IPO, but its quantity is 0 too).
        #     The frontend shows "No available shares" for exactly this
        #     case (shares_outstanding_snapshot == 0) instead of a
        #     misleading dollar figure -- see TournamentDetailModal.tsx.
        # An admin who recognizes a name worth actually listing can
        # always "promote" it later by giving it real shares (there's no
        # dedicated endpoint for that yet -- it'd mean directly updating
        # total_shares_outstanding, which isn't exposed for editing today).
        player = player_service.create_player(db, gamertag=username, total_shares_outstanding=0)
        logger.info("Auto-created placeholder player '%s' for an unmatched Osirion competitor", username)

    if account_id:
        db.add(
            OsirionPlayerMapping(
                id=uuid.uuid4(), osirion_account_id=account_id, osirion_username=username, player_id=player.id
            )
        )
        db.flush()

    return player


def _ensure_real_player(db: Session, osirion_player: dict) -> Player | None:
    """Like `_match_player` above, but for a competitor discovered via a
    qualifier/heat leaderboard BEFORE the Finals happen (see
    `_seed_entrants_from_heat_windows`) -- these get a real, tradeable
    stock at the normal base IPO price/share count
    (player_service.create_player's defaults), not the zero-share
    placeholder `_match_player` uses. The two cases are handled
    differently on purpose: `_match_player`'s zero-share placeholder exists
    only to avoid a leaderboard GAP for a name nobody's ever heard of that
    shows up in FINAL results after the fact (nothing to trade, no time
    left to IPO them); this one is discovered ahead of the event
    specifically so users CAN trade on them before it happens. Someone
    already known (existing accountId mapping or gamertag match,
    including a previous zero-share placeholder) is reused as-is, never
    re-IPO'd or given a second stock."""
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

    escaped_username = username.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    player = db.query(Player).filter(Player.gamertag.ilike(escaped_username, escape="\\")).one_or_none()

    if player is None:
        player = player_service.create_player(db, gamertag=username)
        logger.info("Auto-created a real tradeable stock for qualified entrant '%s'", username)

    if account_id:
        db.add(
            OsirionPlayerMapping(
                id=uuid.uuid4(), osirion_account_id=account_id, osirion_username=username, player_id=player.id
            )
        )
        db.flush()

    return player


def _seed_entrants_from_heat_windows(db: Session, tournament: Tournament, heat_windows: list["AvailableWindow"]) -> int:
    """For a tracked Finals tournament, pulls the leaderboard of each
    sibling heat/qualifier window (same event, but has_cash_payout=False)
    that has ALREADY ended, so the roster of who qualified is known before
    the Finals themselves are played. Each competitor found gets a real
    tradeable stock (see `_ensure_real_player`) and a TournamentEntrant
    row, so the frontend can show "players qualified for this tournament"
    instead of a blank leaderboard while everyone waits for Finals day.
    Safe to call repeatedly -- skips heats that haven't ended yet, and
    skips a competitor already recorded as an entrant."""
    seeded = 0
    now = datetime.now(timezone.utc)
    for heat in heat_windows:
        if heat.end_time is None or not heat.leaderboard_event_id or not heat.leaderboard_event_window_id:
            continue
        end_time = heat.end_time if heat.end_time.tzinfo is not None else heat.end_time.replace(tzinfo=timezone.utc)
        if end_time >= now:
            continue  # this heat hasn't happened yet -- nothing to learn

        try:
            page = 0
            total_pages = 1
            while page < total_pages:
                leaderboard = osirion_client.get_leaderboard_page(
                    heat.leaderboard_event_id, heat.leaderboard_event_window_id, page=page
                )
                total_pages = leaderboard.get("totalPages") or 1
                for entry in leaderboard.get("entries", []):
                    for osirion_player in entry.get("players", []):
                        player = _ensure_real_player(db, osirion_player)
                        if player is None:
                            continue
                        exists = (
                            db.query(TournamentEntrant)
                            .filter_by(tournament_id=tournament.id, player_id=player.id)
                            .one_or_none()
                        )
                        if exists is None:
                            db.add(TournamentEntrant(id=uuid.uuid4(), tournament_id=tournament.id, player_id=player.id))
                            seeded += 1
                page += 1
            db.commit()
        except Exception:  # noqa: BLE001 -- a bad heat leaderboard must not block tracking/syncing the real Finals
            db.rollback()
            logger.exception(
                "Failed to seed qualified entrants from a heat window for tournament %s", tournament.id
            )
    return seeded


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


def _season_quarter_key(when: datetime) -> str:
    """A calendar-quarter stand-in for "competitive season" (Osirion gives
    us no explicit season/chapter identifier to key off of) -- e.g.
    2026-07-15 and 2026-09-01 both map to "2026-Q3". Good enough to decide
    "has a Basic FNCS Finals (or a Globals event) already been tracked
    around the same time as this window", which is the only thing
    auto_track_new_tournaments needs it for."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    quarter = (when.month - 1) // 3 + 1
    return f"{when.year}-Q{quarter}"


def _region_key(regions: list[str]) -> str:
    """Collapses a window's regions list to one comparable key: the single
    region, upper-cased, if there's exactly one -- otherwise "MULTI" for a
    cross-region/ambiguous window (matches the None-region convention used
    when actually tracking the tournament -- see auto_track_new_tournaments)."""
    if len(regions) == 1 and regions[0]:
        return regions[0].strip().upper()
    return "MULTI"


def _has_tournament_in_quarter_and_region(
    db: Session, tournament_type: TournamentType, quarter_key: str, region_key: str
) -> bool:
    rows = db.query(Tournament.start_time, Tournament.region).filter(Tournament.tournament_type == tournament_type).all()
    for start_time, region in rows:
        if start_time is None or _season_quarter_key(start_time) != quarter_key:
            continue
        row_region_key = region.strip().upper() if region else "MULTI"
        if row_region_key == region_key:
            return True
    return False


@dataclass
class AutoTrackResult:
    windows_seen: int = 0
    tracked: int = 0
    skipped_already_tracked: int = 0
    skipped_unclassified: int = 0
    skipped_season_dedup: int = 0
    skipped_not_finals: int = 0  # heat/qualifier (token-only payout) or Zero Build -- never auto-tracked
    entrants_seeded: int = 0
    errors: list[str] = field(default_factory=list)


def auto_track_new_tournaments(db: Session) -> AutoTrackResult:
    """Runs once per background sync pass (see app/main.py's
    _osirion_sync_loop, gated on settings.OSIRION_AUTO_TRACK_ENABLED):
    checks every window Osirion currently has open and auto-tracks the
    ones that are genuinely worth a real dividend payout.

    Two HARD structural filters apply before classification even runs
    (see AvailableWindow's docstring for how each is detected):
      1. Zero Build (ZB) tournaments are never auto-tracked.
      2. A window that doesn't pay real money (has_cash_payout=False --
         i.e. a heat/qualifier/practice round that only pays advancement
         tokens) is never auto-tracked. Within one event's remaining
         cash-paying windows (there can legitimately be more than one --
         e.g. a multi-day LAN where every day pays something), only the
         SINGLE highest-paying window counts as "the Finals" and gets
         tracked; the rest are left alone. This replaces an earlier,
         wrong approach of trusting Osirion's `round` counter, which
         turned out to be unreliable (sometimes stuck at 0) and produced
         both real duplicates ("Round 0" AND "Round 4" for the same
         event) and non-payout heats being tracked as if they were real
         tournaments.

    Only once a window survives both filters does
    tournament_classification_service.classify (admin-editable rules --
    see GET/POST /admin/osirion/classification-rules) get a say in WHICH
    tier it's tracked as. A window that matches no rule, or an explicit
    "exclude" rule (Victory Cups, skin cups, etc.), is left alone -- see
    that module's docstring for why this is a whitelist, not a blocklist.

    Basic FNCS Finals (TournamentType.FNCS_FINALS) gets one extra check:
    the user's rule is "once per season, except during a Globals season"
    -- approximated here as "once per calendar quarter AND region, and
    never in a quarter+region that already has a Global Championship / EWC
    tracked" (see _season_quarter_key/_region_key). Region-aware
    specifically so tracking, say, an EU FNCS Finals for this quarter
    doesn't silently block NAC's or OCE's FNCS Finals for the same
    quarter -- an earlier version of this check ignored region entirely,
    which meant only the first region seen each quarter ever got tracked.

    Region for the payout multiplier (see
    economic_params_service.get_region_multiplier) is only ever a single
    concrete region when the window has EXACTLY one; a genuinely
    cross-region window is tracked with region=None (full, unscaled pool)
    rather than guessing which single region's multiplier should apply.

    Finally, for every Finals window this pass DOES track (or has already
    tracked in an earlier pass, as long as it isn't finalized yet), it
    also looks at that same event's heat/qualifier windows that have
    already ended and pulls their leaderboard once to learn who actually
    qualified -- see _seed_entrants_from_heat_windows -- so the calendar
    can show a real field of competitors before Finals day, each backed by
    a real tradeable stock, not a blank "no results yet" leaderboard.
    """
    result = AutoTrackResult()
    try:
        windows = list_available_windows()
    except OsirionApiError as exc:
        result.errors.append(str(exc))
        return result

    result.windows_seen = len(windows)

    mappings = db.query(OsirionTournamentMapping).all()
    tracked_keys = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in mappings}
    tracked_key_to_tournament_id = {
        (m.leaderboard_event_id, m.leaderboard_event_window_id): m.tournament_id for m in mappings
    }

    windows_by_event: dict[str, list[AvailableWindow]] = {}
    for w in windows:
        windows_by_event.setdefault(w.event_id, []).append(w)

    eligible_by_event: dict[str, list[AvailableWindow]] = {}
    for event_id, group in windows_by_event.items():
        eligible = [w for w in group if w.has_cash_payout and not w.is_zero_build]
        result.skipped_not_finals += len(group) - len(eligible)
        if eligible:
            eligible_by_event[event_id] = eligible

    for event_id, eligible in eligible_by_event.items():
        heat_windows = [w for w in windows_by_event[event_id] if not w.has_cash_payout]

        already_tracked_window = next(
            (w for w in eligible if (w.leaderboard_event_id, w.leaderboard_event_window_id) in tracked_keys), None
        )
        if already_tracked_window is not None:
            result.skipped_already_tracked += 1
            tournament_id = tracked_key_to_tournament_id.get(
                (already_tracked_window.leaderboard_event_id, already_tracked_window.leaderboard_event_window_id)
            )
            tournament = db.get(Tournament, tournament_id) if tournament_id else None
            if tournament is not None and tournament.status != TournamentStatus.FINALIZED and heat_windows:
                result.entrants_seeded += _seed_entrants_from_heat_windows(db, tournament, heat_windows)
            continue

        window = max(eligible, key=lambda w: w.top_cash_amount)
        key = (window.leaderboard_event_id, window.leaderboard_event_window_id)
        if not window.leaderboard_event_id or not window.leaderboard_event_window_id:
            result.skipped_not_finals += 1
            continue

        tournament_type = tournament_classification_service.classify(db, window.classification_text)
        if tournament_type is None:
            result.skipped_unclassified += 1
            continue

        region_key = _region_key(window.regions)
        if tournament_type == TournamentType.FNCS_FINALS:
            quarter_key = _season_quarter_key(window.begin_time or datetime.now(timezone.utc))
            already_has_globals = _has_tournament_in_quarter_and_region(
                db, TournamentType.GLOBAL_CHAMPIONSHIP, quarter_key, region_key
            )
            already_has_fncs_finals = _has_tournament_in_quarter_and_region(
                db, TournamentType.FNCS_FINALS, quarter_key, region_key
            )
            if already_has_globals or already_has_fncs_finals:
                result.skipped_season_dedup += 1
                continue

        region = window.regions[0] if len(window.regions) == 1 else None
        try:
            mapping = track_tournament(
                db,
                name=window.display_name,
                tournament_type=tournament_type,
                region=region,
                window=window,
                created_by_admin_id=None,
            )
            tracked_keys.add(key)
            result.tracked += 1
            logger.info("Auto-tracked new tournament '%s' as %s", window.display_name, tournament_type.value)

            if heat_windows:
                tournament = db.get(Tournament, mapping.tournament_id)
                if tournament is not None:
                    result.entrants_seeded += _seed_entrants_from_heat_windows(db, tournament, heat_windows)
        except Exception as exc:  # noqa: BLE001 -- one bad window must not abort the whole pass
            db.rollback()
            result.errors.append(f"{window.display_name}: {exc}")
            logger.exception("Auto-track failed for window %s", window.display_name)

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
