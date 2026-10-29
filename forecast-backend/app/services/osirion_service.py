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
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations import osirion_client
from app.integrations.osirion_client import OsirionApiError
from app.models.osirion import OsirionPlayerMapping, OsirionSeededHeatWindow, OsirionTournamentMapping, PlayerAlias
from app.models.player import Player
from app.models.tournament import (
    PlacementResult,
    ResultSource,
    Tournament,
    TournamentEntrant,
    TournamentResultArchive,
    TournamentStatus,
    TournamentType,
)
from app.services import player_service, tournament_classification_service, tournament_service
from app.services.player_identity import skeleton

logger = logging.getLogger("forecast.osirion")

# Per explicit product direction (Sept 2026): the tradeable roster was
# growing far larger than expected once every region's weekly Cash Cup
# (NAC, NAW, EU, BR, OCE, ME, ASIA, each in multiple formats) was counted
# as a real Finals tier alongside the genuinely rare top-tier events. For
# now, only track region-scoped tournaments (Cash Cup / FNCS Division /
# FNCS Finals / generic Cash Cup) for these two regions -- easy to expand
# later by just adding more codes here (these match the exact strings
# Osirion returns in a window's `regions` list, and the same codes used by
# economic_params_service.DEFAULT_REGION_MULTIPLIERS).
ALLOWED_TRACKING_REGIONS: set[str] = {"NAC", "EU"}

# LAN/global-tier tournaments (EWC, FNCS Global Championship, Majors) are
# NEVER region-restricted -- they're inherently cross-region events (often
# tracked with region=None / a "MULTI" region key, see _region_key), and
# the whole point of a LAN is that it draws from every region at once. The
# ALLOWED_TRACKING_REGIONS scope above only applies to the per-region
# recurring tiers (Cash Cup, FNCS Finals).
_REGION_EXEMPT_TOURNAMENT_TYPES: frozenset[TournamentType] = frozenset(
    {TournamentType.GLOBAL_CHAMPIONSHIP, TournamentType.MAJOR}
)


def _in_tracking_region_scope(tournament_type: TournamentType, regions: list[str]) -> bool:
    """True if this window should be tracked given the current
    ALLOWED_TRACKING_REGIONS scope -- LAN/global tiers always pass
    regardless of region; everything else must resolve to exactly one
    region that's in the allow-list (a cross-region/ambiguous "MULTI" key
    for a non-LAN tier is treated as out of scope, not guessed into
    scope)."""
    if tournament_type in _REGION_EXEMPT_TOURNAMENT_TYPES:
        return True
    return _region_key(regions) in ALLOWED_TRACKING_REGIONS


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
    # The original, unflattened Osirion dicts this window came from --
    # kept only so track_tournament can hand them to
    # TournamentResultArchive at track time (see that model's docstring
    # for why: a permanent record of Osirion's own tournament metadata in
    # case their API ever purges/rotates it). Not used for any actual
    # classification/tracking decision -- those all go through the typed
    # fields above.
    raw_tournament: dict = field(default_factory=dict)
    raw_event_window: dict = field(default_factory=dict)

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


def _pick_score_location(score_locations: list[dict]) -> dict:
    """Picks which of a window's scoreLocations is authoritative for
    classification/payout/tracking purposes. Most windows have exactly
    one, or one flagged isMain that also carries the real payout table --
    but a multi-day cumulative event (observed on a real FNCS Global
    Championship window: two daily isMain leaderboards, EACH with an
    empty payoutTables array, plus a separate non-main scoreLocation
    named "cumulative" that carries the actual $2,000,000 payout table
    spanning both days) breaks the naive "just use isMain" heuristic --
    it silently makes a real, huge-money Finals event look like it has no
    cash payout at all, so it never gets classified, tracked, or synced.

    Prefer whichever scoreLocation actually HAS a real cash payout table;
    only fall back to isMain/first when none of them do (a genuine
    heat/qualifier window with no cash payouts, or a window where Osirion
    hasn't published payouts yet)."""
    with_cash = [sl for sl in score_locations if _cash_payout_info(sl)[0]]
    if with_cash:
        return next((sl for sl in with_cash if sl.get("isMain")), with_cash[0])
    return next((sl for sl in score_locations if sl.get("isMain")), score_locations[0])


def list_available_windows(region: str | None = None, include_historic_data: bool = False) -> list[AvailableWindow]:
    """Flattens Osirion's /v1/tournaments response into one row per
    trackable window. See _pick_score_location for which of a window's
    scoreLocations gets used.

    IMPORTANT: Osirion's listing is PER REGION and silently defaults to EU
    when no `region` is sent -- so a call with region=None used to return
    only EU events (plus the shared ONSITE/LAN ones), and every NAC-only
    tournament was invisible to auto-tracking, the historical backfill and
    the discovery scripts. With region=None this now queries every region in
    ALLOWED_TRACKING_REGIONS and merges the results (LAN events appear under
    every region, so rows are de-duplicated by window). Passing an explicit
    `region` behaves exactly as before."""
    if region is not None:
        return _list_windows_for_region(region, include_historic_data)

    merged: list[AvailableWindow] = []
    seen: set[tuple] = set()
    for r in sorted(ALLOWED_TRACKING_REGIONS):
        for w in _list_windows_for_region(r, include_historic_data):
            key = (w.event_id, w.event_window_id, w.leaderboard_event_id, w.leaderboard_event_window_id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(w)
    return merged


def _list_windows_for_region(region: str | None, include_historic_data: bool) -> list[AvailableWindow]:
    tournaments = osirion_client.list_tournaments(region=region, include_historic_data=include_historic_data)
    windows: list[AvailableWindow] = []

    for tournament in tournaments:
        name = _display_name(tournament)
        event_id = tournament.get("eventId", "")
        regions = tournament.get("regions", [])
        # NAC and EU run identically named events on the same dates; tag NAC-only ones so the two are tellable apart
        # in lists (some NAC titles already start with "[NAC]" from Osirion -- don't double-tag those).
        if [r.upper() for r in regions] == ["NAC"] and "[nac]" not in name.lower():
            name = f"[NAC] {name}"

        for event_window in tournament.get("eventWindows", []):
            score_locations = event_window.get("scoreLocations", [])
            if not score_locations:
                continue
            chosen = _pick_score_location(score_locations)
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
                    raw_tournament=tournament,
                    raw_event_window=event_window,
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
    is_historical_archive: bool = False,
) -> OsirionTournamentMapping:
    """Creates a new internal Tournament (result_source=API_IMPORT) plus
    its OsirionTournamentMapping, in one call. `name`/`tournament_type`
    are chosen by the admin -- Osirion has no typed FNCS-vs-Cash-Cup field
    to trust (see this module's docstring) -- everything else comes from
    the picked `window` (see list_available_windows).

    `is_historical_archive=True` (only ever passed by
    backfill_historical_tournaments) marks this as an already-decided past
    result being backfilled purely for its players' stock/career-history
    value -- see Tournament.is_historical_archive's docstring for what
    that flag actually changes."""
    tournament = tournament_service.create_tournament(
        db,
        name=name,
        tournament_type=tournament_type,
        region=region,
        start_time=window.begin_time,
        end_time=window.end_time,
        created_by_admin_id=created_by_admin_id,
        result_source=ResultSource.API_IMPORT,
        is_historical_archive=is_historical_archive,
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

    # Permanently archive Osirion's own raw tournament/window metadata
    # right now, while we have it -- see TournamentResultArchive's
    # docstring for why. raw_leaderboard_entries gets filled in by the
    # first successful sync (see sync_tournament's _archive_raw_results
    # call); nothing to put there yet.
    if window.raw_tournament or window.raw_event_window:
        db.add(
            TournamentResultArchive(
                id=uuid.uuid4(),
                tournament_id=tournament.id,
                raw_tournament_metadata={
                    "tournament": window.raw_tournament,
                    "event_window": window.raw_event_window,
                },
            )
        )

    db.commit()
    db.refresh(mapping)
    return mapping


_CLAN_TAG_RE = re.compile(r"\[[^\]]*\]")
_EXTRA_WHITESPACE_RE = re.compile(r"\s+")


def clean_gamertag(raw: str) -> str:
    """Osirion's `username` sometimes carries a bracketed clan/LAN tag
    baked into the same string as the display name -- e.g.
    "[FNCSGC26] PlayerName" or "PlayerName [EW2026]" -- plus occasional
    extra/inconsistent whitespace around it. None of that is part of the
    competitor's actual name, but with no cleaning it used to get stored
    verbatim as the permanent, globally-unique `Player.gamertag`: ugly on
    the leaderboard, and a real risk of the SAME real player getting two
    different Player rows/stocks if one sync sees them tagged and another
    (or a later event) doesn't -- see `_match_player`'s accountId-based
    OsirionPlayerMapping cache for why that risk is otherwise contained
    once a player IS matched this way (capitalization/tag changes AFTER
    the first successful match never re-run this string matching, since
    the cached mapping is checked first).

    Strips every bracketed `[...]` segment and collapses/trims whitespace.
    Falls back to the original raw string if cleaning would leave nothing
    (e.g. a username that was somehow only a bracket tag) -- a Player
    always needs a non-empty gamertag."""
    cleaned = _EXTRA_WHITESPACE_RE.sub(" ", _CLAN_TAG_RE.sub("", raw)).strip()
    return cleaned or raw.strip()


def _match_player(db: Session, osirion_player: dict, create_missing: bool = True) -> Player | None:
    """`create_missing=False` (only ever passed by scripts/resync_roster.py's
    --with-history mode) makes this strictly look-up-only: someone who matches no
    existing accountId mapping and no existing gamertag yields None instead of a
    brand-new Player. That lets an out-of-scope tournament's results be attached to
    players already on the roster without ever growing the roster itself.

    Finds (or creates) the Player for one Osirion competitor -- used
    both for entrants discovered ahead of Finals (via a concluded heat's
    leaderboard, see `_seed_entrants_from_heat_windows`) and for anyone
    who only shows up once real placement results come in.

    Historical note: this used to create a ZERO-share placeholder stock
    ("nothing to trade, no time left to IPO them") for anyone discovered
    only in final results, distinct from a separate `_ensure_real_player`
    helper that gave qualified-ahead-of-time entrants a real stock. Per
    explicit product direction, that distinction is gone -- ANYONE found
    in ANY tracked (real cash-payout) tournament, whether discovered via a
    pre-Finals qualifying heat or only in the Finals results themselves,
    now gets a real, tradeable stock at the normal base IPO
    price/share count (player_service.create_player's defaults). An admin
    can still hand-adjust an individual player's share count/price later
    if a specific listing warrants it -- there's no dedicated endpoint for
    that, it means directly updating total_shares_outstanding/ipo_price.
    Someone already known (existing accountId mapping or gamertag match)
    is reused as-is, never re-IPO'd or given a second stock."""
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
        # create a player without at least a gamertag to show.
        return None

    # Clean BEFORE matching, not just before creating -- so a name that's
    # tagged this sync but was clean (or tagged differently) on some
    # earlier sync still matches the same existing Player.gamertag rather
    # than silently creating a second stock for the same real competitor.
    # See clean_gamertag's docstring.
    cleaned_username = clean_gamertag(username)

    # Known alternate name (e.g. a pro's LAN account name registered from the linker sheet --
    # scripts/merge_from_linker.py): checked BEFORE gamertag matching/creation, because a linked
    # player's gamertag is the pro name we list ("Shxrk"), not the name this account plays under
    # ("AUR shxrkÿ"). Compared by skeleton, so tags/case/accents/look-alike letters don't matter.
    alias = db.query(PlayerAlias).filter(PlayerAlias.alias_key == skeleton(username)).one_or_none()
    if alias is not None:
        aliased = db.get(Player, alias.player_id)
        if aliased is not None and not aliased.gamertag.startswith("[MERGED INTO"):
            if account_id:
                db.add(
                    OsirionPlayerMapping(
                        id=uuid.uuid4(), osirion_account_id=account_id, osirion_username=username, player_id=aliased.id
                    )
                )
                db.flush()
            return aliased

    # Escape SQL LIKE wildcards (% and _) that could theoretically appear
    # in a Fortnite display name -- ilike() would otherwise treat them as
    # pattern characters instead of literal ones.
    escaped_username = cleaned_username.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    player = db.query(Player).filter(Player.gamertag.ilike(escaped_username, escape="\\")).one_or_none()

    if player is None:
        if not create_missing:
            return None
        player = player_service.create_player(db, gamertag=cleaned_username)
        logger.info("Auto-created a real tradeable stock for Osirion competitor '%s' (raw: '%s')", cleaned_username, username)

    if account_id:
        db.add(
            OsirionPlayerMapping(
                id=uuid.uuid4(), osirion_account_id=account_id, osirion_username=username, player_id=player.id
            )
        )
        db.flush()

    return player


def _seed_entrants_from_heat_windows(db: Session, tournament: Tournament, heat_windows: list["AvailableWindow"]) -> int:
    """INTENTIONALLY DISABLED (returns 0 immediately, does nothing) -- see
    the user-directed fix in this function's git history for the full
    reasoning. This used to pull the FULL leaderboard of every sibling
    heat/qualifier window (same event, has_cash_payout=False) so the
    "qualified entrants" preview could show a field before Finals day,
    auto-IPOing (via `_match_player`) every competitor found in the
    process. Real qualifier leaderboards can have tens of thousands of
    entrants with no page cap on the walk here (unlike sync_tournament's
    OSIRION_MAX_PAGES_PER_TOURNAMENT_PER_SYNC limit on the real Finals
    leaderboard) -- this turned out to be THE reason 89,702 Player rows
    existed in production despite the Tournament-tracking gate itself
    (has_cash_payout, see auto_track_new_tournaments) already correctly
    limiting real tracked tournaments to genuine cash-payout Finals
    events with ~40-100 real entrants. The explicit decision is: only
    Finals-tier tournaments with real cash payouts should ever create or
    grow the tradeable player roster; qualifiers/heats should not,
    regardless of how large or repeat-heavy their own field is. The
    "qualified entrants" preview this fed simply goes back to showing
    nothing until real Finals results come in -- see
    TournamentDetailModal.tsx's `entrants.length > 0` fallback, which
    already handles an empty/never-populated entrants list gracefully.
    Left in place (rather than deleted) so the call sites, the
    AutoTrackResult.entrants_seeded field, and the OsirionSeededHeatWindow
    dedup table don't need to change; this is now always a no-op."""
    return 0


def _seed_entrants_from_heat_windows_DISABLED(db: Session, tournament: Tournament, heat_windows: list["AvailableWindow"]) -> int:
    """Original implementation, kept only for reference -- never called."""
    seeded = 0
    now = datetime.now(timezone.utc)
    for heat in heat_windows:
        if heat.end_time is None or not heat.leaderboard_event_id or not heat.leaderboard_event_window_id:
            continue
        end_time = heat.end_time if heat.end_time.tzinfo is not None else heat.end_time.replace(tzinfo=timezone.utc)
        if end_time >= now:
            continue  # this heat hasn't happened yet -- nothing to learn

        # A heat's results can never change once it has ended -- if we've
        # already walked this exact leaderboard to completion before (any
        # tournament, any earlier pass), there's nothing new to learn by
        # fetching it again. Before this check existed, every 45s sync
        # pass re-fetched every ended heat's ENTIRE leaderboard forever,
        # for as long as its Finals tournament stayed un-finalized -- pure
        # waste against Osirion's shared rate-limit budget (see
        # osirion_client.py) and a real contributor to syncs getting
        # starved/rate-limited.
        already_seeded = (
            db.query(OsirionSeededHeatWindow)
            .filter_by(
                leaderboard_event_id=heat.leaderboard_event_id,
                leaderboard_event_window_id=heat.leaderboard_event_window_id,
            )
            .one_or_none()
        )
        if already_seeded is not None:
            continue

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
                        player = _match_player(db, osirion_player)
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
            db.add(
                OsirionSeededHeatWindow(
                    id=uuid.uuid4(),
                    leaderboard_event_id=heat.leaderboard_event_id,
                    leaderboard_event_window_id=heat.leaderboard_event_window_id,
                )
            )
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


# Osirion's trackedStats key naming isn't documented/guaranteed stable
# across seasons/modes -- try each candidate per session and use whichever
# one is actually present, rather than assuming one fixed name forever.
_ELIMINATION_STAT_KEYS = ("TEAM_ELIMS_STAT_INDEX", "PLAYER_ELIMS_STAT_INDEX", "Eliminations", "eliminations")


def _extract_eliminations(entry: dict) -> int | None:
    """Best-effort total eliminations for one leaderboard entry, summed
    across every session in its sessionHistory (a window can span more
    than one game). Returns None (not 0) when sessionHistory is empty or
    carries no recognizable elimination stat, so the UI/DB can tell "no
    data available" apart from "genuinely zero eliminations"."""
    sessions = entry.get("sessionHistory") or []
    if not sessions:
        return None
    total = 0
    found_any = False
    for session in sessions:
        stats = session.get("trackedStats") or {}
        for key in _ELIMINATION_STAT_KEYS:
            if key in stats:
                try:
                    total += int(stats[key])
                    found_any = True
                except (TypeError, ValueError):
                    pass
                break
    return total if found_any else None


def _archive_raw_results(db: Session, tournament_id: uuid.UUID, entries: list[dict]) -> None:
    """Upserts this tournament's TournamentResultArchive with the raw
    leaderboard entries just fetched -- see that model's docstring for
    why. Safe to call every sync pass: each call simply replaces the
    previous snapshot with the latest, more-complete one, and once the
    tournament finalizes, sync_tournament stops running for it entirely --
    so whatever's stored here at that point is permanent."""
    archive = db.query(TournamentResultArchive).filter_by(tournament_id=tournament_id).one_or_none()
    if archive is None:
        archive = TournamentResultArchive(id=uuid.uuid4(), tournament_id=tournament_id)
        db.add(archive)
    archive.raw_leaderboard_entries = entries


@dataclass
class SyncResult:
    tournament_id: uuid.UUID
    entries_seen: int = 0
    matched: int = 0
    unmatched_usernames: list[str] = field(default_factory=list)
    finalized: bool = False
    error: str | None = None
    # LAN hold (see sync_tournament): accounts in a LAN/global event that matched no existing
    # player/alias and were therefore NOT auto-created -- [(accountId, username, rank)].
    unlinked: list = field(default_factory=list)


# A finals lobby is ~100 players (Reload 40). Anything with more than this many ENTRIES is an open field.
_MAX_FINALS_FIELD_ENTRIES = 200


def _lan_hold_applies(tournament: Tournament, skip_finalize: bool) -> bool:
    """True for a LIVE (dividend-paying) sync of a LAN/global-tier tournament.

    LAN accounts are separate Epic accounts with different ids/names than the pro's main account, so
    a LAN account nobody linked beforehand would otherwise be auto-created as a brand-new stock --
    and since finalization pays dividends to whoever holds the shares at that moment, a placement on
    a duplicate stock is paid to the wrong holders and can't be repaired afterwards. For these events
    unknown accounts are therefore held back (not created) and finalization waits until they are
    linked with scripts/link_lan_accounts.py. Backfills (skip_finalize=True) never pay dividends and
    keep the old create-as-you-go behavior."""
    if skip_finalize or not getattr(settings, "LAN_HOLD_UNLINKED_ACCOUNTS", True):
        return False
    return tournament.tournament_type in _REGION_EXEMPT_TOURNAMENT_TYPES


def sync_tournament(
    db: Session, mapping: OsirionTournamentMapping, skip_finalize: bool = False, create_missing_players: bool = True
) -> SyncResult:
    """`create_missing_players=False` (only ever passed by scripts/resync_roster.py's
    --with-history mode) attaches placements only to players that already exist; it never
    creates a new Player -- see `_match_player`.

    `skip_finalize=True` (only ever passed by backfill_historical_tournaments)
    still does everything a normal sync does -- walks the full leaderboard,
    matches/creates real Player stocks, writes real PlacementResult rows,
    archives the raw results -- but once the window is fully synced, marks
    the tournament FINALIZED directly instead of calling
    tournament_service.finalize_tournament. That's the one and only thing
    finalize_tournament does beyond flipping status: it creates
    DividendPayout rows and enqueues real payouts to whoever currently
    holds shares. For an already-decided historical result there was never
    a "before the result was known" moment for a real payout to mean
    anything, and paying one out anyway is exactly the exploit this app's
    dividend design has to avoid -- see reconcile_stale_tournaments.py's
    module docstring for a real incident this same gap caused."""
    result = SyncResult(tournament_id=mapping.tournament_id)
    tournament = db.get(Tournament, mapping.tournament_id)
    if tournament is None or tournament.status == TournamentStatus.FINALIZED:
        return result

    now = datetime.now(timezone.utc)
    lan_hold = _lan_hold_applies(tournament, skip_finalize)
    if lan_hold:
        create_missing_players = False

    # SQLite (demo mode) drops tzinfo on DateTime(timezone=True) columns on
    # read-back -- see password_reset_service.confirm_reset for the same
    # fix and why a naive value here is always UTC, never local time.
    # No-op on Postgres, where these are already tz-aware.
    begin_time = mapping.window_begin_time
    if begin_time is not None and begin_time.tzinfo is None:
        begin_time = begin_time.replace(tzinfo=timezone.utc)
    if begin_time is not None and begin_time > now:
        # The window hasn't started -- there's nothing to fetch yet, and
        # every request here counts against Osirion's shared rate-limit
        # budget (see osirion_client.py), so don't spend one on a
        # leaderboard that can only come back empty.
        return result

    end_time = mapping.window_end_time
    if end_time is not None and end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    window_ended = end_time is not None and end_time < now

    # While still in progress, cap how many pages one pass pulls for this
    # ONE tournament so a single huge field can't monopolize the whole
    # pass (and the shared rate limit) and starve every other tracked
    # tournament of updates -- it just makes steady incremental progress
    # across several 45s passes instead. Once the window has actually
    # ended there's no "next pass will catch up" any more for THIS
    # tournament's finalization -- walk every page no matter how long it
    # takes, so finalizing is never based on a partial field.
    max_pages = None if window_ended else settings.OSIRION_MAX_PAGES_PER_TOURNAMENT_PER_SYNC

    reached_end_of_leaderboard = False
    try:
        page = 0
        total_pages = 1
        all_entries: list[dict] = []
        while page < total_pages and (max_pages is None or page < max_pages):
            leaderboard = osirion_client.get_leaderboard_page(
                mapping.leaderboard_event_id, mapping.leaderboard_event_window_id, page=page
            )
            total_pages = leaderboard.get("totalPages") or 1
            entries = leaderboard.get("entries", [])
            all_entries.extend(entries)

            # Open-field guard (live path, non-LAN only): a finals lobby is <=~100 players, so a leaderboard
            # with far more than a couple hundred entries is an open cup/qualifier that must never become
            # tradeable players (that is how the roster once reached 89k). Pre-start tracking of upcoming
            # events (scripts/track_upcoming_finals.py) relies on this: a mis-tracked open event is hidden
            # the moment its field is visible, before a single player is created.
            if (
                page == 0
                and not skip_finalize
                and tournament.tournament_type not in _REGION_EXEMPT_TOURNAMENT_TYPES
                and total_pages > 1
                and len(entries) * (total_pages - 1) > _MAX_FINALS_FIELD_ENTRIES
            ):
                tournament.is_historical_archive = True
                db.commit()
                result.error = (
                    f"open field (~{len(entries) * (total_pages - 1)}+ entries over {total_pages} pages) -- not a finals; "
                    f"tournament hidden and not synced"
                )
                logger.warning("Tournament %s (%s): %s", tournament.id, tournament.name, result.error)
                return result

            for entry in entries:
                rank = entry.get("rank")
                if not rank or rank <= 0:
                    continue
                points = _to_decimal(entry.get("pointsEarned"))
                team_id = entry.get("teamId")
                percentile = _to_decimal(entry.get("percentile"))
                eliminations = _extract_eliminations(entry)
                for osirion_player in entry.get("players", []):
                    result.entries_seen += 1
                    player = _match_player(db, osirion_player, create_missing=create_missing_players)
                    if player is None:
                        if osirion_player.get("username"):
                            result.unmatched_usernames.append(osirion_player["username"])
                        if lan_hold:
                            result.unlinked.append(
                                (osirion_player.get("accountId"), osirion_player.get("username"), rank)
                            )
                        continue
                    tournament_service.upsert_placement_result(
                        db,
                        tournament_id=tournament.id,
                        player_id=player.id,
                        placement=rank,
                        points=points,
                        eliminations=eliminations,
                        team_id=team_id,
                        percentile=percentile,
                        raw_stats=entry,
                    )
                    result.matched += 1

            # Commit after EVERY page, not just once at the very end. This
            # is the actual fix for tournaments getting perpetually stuck
            # "syncing" and never finalizing: previously, a rate-limited or
            # network failure on (say) page 30 of 60 rolled back and threw
            # away ALL 30 already-fetched pages' work, and the next pass
            # would hit the exact same rate limit at the exact same spot --
            # spinning in place forever instead of ever making forward
            # progress. Committing per page means a later failure only
            # costs the rest of THIS pass; everything already processed is
            # safely persisted and the next pass resumes making progress
            # rather than starting over.
            mapping.last_synced_at = datetime.now(timezone.utc)
            db.commit()

            page += 1

        reached_end_of_leaderboard = page >= total_pages

        # Permanently capture the raw response fetched so far too -- see
        # TournamentResultArchive's docstring. Includes entries that never
        # matched a Player, unlike the PlacementResult rows above. Safe to
        # overwrite with a partial (page-capped) pull -- it's still the
        # freshest snapshot of the top of the leaderboard, and gets
        # replaced by a more complete one on a later pass.
        _archive_raw_results(db, tournament.id, all_entries)
        mapping.last_sync_complete = reached_end_of_leaderboard
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

    # Only finalize once a pass has walked the ENTIRE leaderboard for a
    # window that has actually ended -- never on a partial/page-capped
    # pull. Finalizing on incomplete data would permanently lock in a
    # missing tail of the field (finalize_tournament stops this
    # tournament from ever syncing again), which is worse than just taking
    # one more 45s pass to get a complete picture.
    #
    # Whether there's anything TO finalize is decided from the DB, not
    # from `result.matched` (this pass's local counter) -- a real Cash
    # Cup/FNCS window can have thousands of entrants against our much
    # smaller tracked roster, so it's normal and common for a fully
    # completed tournament to have zero of our players anywhere in its
    # field. Gating on `result.matched > 0` used to mean that case never
    # finalized: finalize_tournament requires >=1 PlacementResult and
    # raises ValueError otherwise, so every single sync pass forever would
    # re-walk the whole (already-fully-synced) leaderboard, hit the same
    # ValueError, and leave the tournament stuck showing as perpetually
    # "Live"/"Sync stalled" on the frontend even though it finished
    # normally and simply had no involvement from anyone we track.
    if reached_end_of_leaderboard and window_ended and lan_hold and result.unlinked:
        # Never pay dividends on an incomplete/misattributed LAN field. Resolve with
        # scripts/link_lan_accounts.py; the next sync pass (45s) finalizes automatically.
        result.error = (
            f"finalization HELD: {len(result.unlinked)} LAN account(s) not linked to a player "
            f"(run scripts/link_lan_accounts.py): "
            + ", ".join(f"{u or a} (#{r})" for a, u, r in result.unlinked[:10])
        )
        logger.warning("Tournament %s: %s", tournament.id, result.error)
        return result

    if reached_end_of_leaderboard and window_ended:
        has_any_results = (
            db.query(PlacementResult.id).filter(PlacementResult.tournament_id == tournament.id).first() is not None
        )
        if not has_any_results:
            # Nobody we track ever placed here -- nothing for
            # finalize_tournament to do, and nothing will ever revisit
            # this tournament once it stops being synced. Retire it the
            # same no-payout way `skip_finalize` does, purely so it drops
            # off the live calendar / "Happening Now" instead of sitting
            # stuck forever.
            tournament.status = TournamentStatus.FINALIZED
            db.commit()
            result.finalized = True
        elif skip_finalize:
            # Historical backfill path: lock in FINALIZED (so nothing ever
            # re-syncs or tries to finalize this again) WITHOUT creating a
            # single DividendPayout row. See this function's docstring.
            tournament.status = TournamentStatus.FINALIZED
            db.commit()
            result.finalized = True
        else:
            try:
                tournament_service.finalize_tournament(db, tournament.id)
                result.finalized = True
            except ValueError as exc:
                # Shouldn't happen now that has_any_results is checked
                # above, but leave this as a safety net -- leave it for
                # the next sync rather than crashing the whole loop.
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
    skipped_region: int = 0  # classified fine, but outside ALLOWED_TRACKING_REGIONS and not a LAN/global tier
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

    A THIRD filter applies right after classification: see
    `_in_tracking_region_scope`/`ALLOWED_TRACKING_REGIONS` above this
    function -- a region-scoped tier (Cash Cup, FNCS Finals) is only
    auto-tracked for the currently-allowed regions; LAN/global tiers
    (EWC, FNCS Global Championship, Majors) always pass regardless of
    region. This is the fix for the roster growing far past what a handful
    of genuinely rare Finals/LAN events would ever produce -- most of the
    volume was coming from tracking every region's own weekly Cash Cup.

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

    NOTE: this used to also pull each Finals window's sibling heat/qualifier
    leaderboards (see _seed_entrants_from_heat_windows) to pre-seed a
    "qualified entrants" preview before Finals day -- that's now disabled.
    Walking a qualifier's full leaderboard (often tens of thousands of
    entrants, heavy on one-off/repeat names, with no cash payout of its
    own) and auto-IPOing everyone found was the actual cause of the
    player roster growing to 89,702 rows, even though tournament TRACKING
    itself was already correctly limited to genuine cash-payout Finals
    events. Only a tournament's own Finals leaderboard (walked in
    sync_tournament, page-capped, ~40-100 real entrants) creates/grows
    the tradeable player roster now.
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

        if not _in_tracking_region_scope(tournament_type, window.regions):
            result.skipped_region += 1
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


@dataclass
class BackfillCandidate:
    """One already-concluded, real cash-paying window that isn't tracked
    yet -- everything find_historical_backfill_candidates needs to know to
    let an admin preview it, and everything backfill_historical_tournaments
    needs to actually track+sync it."""

    window: AvailableWindow
    tournament_type: TournamentType


@dataclass
class BackfillScanResult:
    candidates: list[BackfillCandidate] = field(default_factory=list)
    events_seen: int = 0
    already_tracked: int = 0
    skipped_not_eligible: int = 0  # heat/qualifier, Zero Build, no leaderboard ids, or not concluded yet
    skipped_unclassified: int = 0
    errors: list[str] = field(default_factory=list)


def find_historical_backfill_candidates(db: Session) -> BackfillScanResult:
    """Read-only scan (makes no Tournament/Player/etc. writes -- the one
    exception is tournament_classification_service.classify's own
    idempotent seed_default_rules() call, same as every other classify()
    caller) over Osirion's full historical listing
    (includeHistoricData=true), returning every already-decided, real
    cash-paying, not-yet-tracked window -- i.e. exactly what
    backfill_historical_tournaments would go on to track+sync, without
    actually doing it. Meant for a dry-run preview (see
    scripts/backfill_historical_market.py) before committing to what can
    be a large, slow, many-Osirion-request operation.

    Eligibility mirrors auto_track_new_tournaments (has_cash_payout, not
    Zero Build, one window per event picked by top payout, must classify
    to a real tier, must pass the current ALLOWED_TRACKING_REGIONS/LAN
    scope -- see _in_tracking_region_scope) with two differences: no
    season/region dedup (we want every distinct past edition, not just one
    per season), and the window must have actually ENDED -- anything still
    open belongs to the live auto-track path, not history."""
    scan = BackfillScanResult()
    try:
        windows = list_available_windows(include_historic_data=True)
    except OsirionApiError as exc:
        scan.errors.append(str(exc))
        return scan

    now = datetime.now(timezone.utc)
    existing_keys = {
        (m.leaderboard_event_id, m.leaderboard_event_window_id) for m in db.query(OsirionTournamentMapping).all()
    }

    windows_by_event: dict[str, list[AvailableWindow]] = {}
    for w in windows:
        windows_by_event.setdefault(w.event_id, []).append(w)

    for event_id, group in windows_by_event.items():
        eligible = [w for w in group if w.has_cash_payout and not w.is_zero_build]
        if not eligible:
            scan.skipped_not_eligible += len(group)
            continue

        window = max(eligible, key=lambda w: w.top_cash_amount)
        scan.events_seen += 1

        if not window.leaderboard_event_id or not window.leaderboard_event_window_id:
            scan.skipped_not_eligible += 1
            continue

        key = (window.leaderboard_event_id, window.leaderboard_event_window_id)
        if key in existing_keys:
            scan.already_tracked += 1
            continue

        end_time = window.end_time
        if end_time is not None and end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        if end_time is None or end_time >= now:
            scan.skipped_not_eligible += 1
            continue

        tournament_type = tournament_classification_service.classify(db, window.classification_text)
        if tournament_type is None:
            scan.skipped_unclassified += 1
            continue

        if not _in_tracking_region_scope(tournament_type, window.regions):
            scan.skipped_not_eligible += 1
            continue

        scan.candidates.append(BackfillCandidate(window=window, tournament_type=tournament_type))

    return scan


@dataclass
class BackfillResult:
    tracked: int = 0
    total_entries_seen: int = 0
    total_matched: int = 0
    tracked_details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def backfill_historical_tournaments(db: Session, candidates: list[BackfillCandidate]) -> BackfillResult:
    """Actually tracks+syncs the given (already-vetted, see
    find_historical_backfill_candidates) historical windows: creates a
    real tradeable Player stock for every competitor found (same
    _match_player path as a live sync -- see that function's docstring),
    writes real PlacementResult rows, permanently archives the raw
    leaderboard (TournamentResultArchive), and marks each tournament
    is_historical_archive=True + FINALIZED -- all via track_tournament +
    sync_tournament(skip_finalize=True), so NO DividendPayout row is ever
    created for a backfilled result. See sync_tournament's docstring for
    exactly why that matters.

    Caller (scripts/backfill_historical_market.py) decides how many
    candidates to pass in one call -- each one walks a full paginated
    leaderboard, so a huge batch is best worked through across several
    calls rather than all at once."""
    result = BackfillResult()
    for candidate in candidates:
        window = candidate.window
        region = window.regions[0] if len(window.regions) == 1 else None
        try:
            mapping = track_tournament(
                db,
                name=window.display_name,
                tournament_type=candidate.tournament_type,
                region=region,
                window=window,
                created_by_admin_id=None,
                is_historical_archive=True,
            )
            sync_result = sync_tournament(db, mapping, skip_finalize=True)
            result.tracked += 1
            result.total_entries_seen += sync_result.entries_seen
            result.total_matched += sync_result.matched
            result.tracked_details.append(
                f"{window.display_name!r}: entries_seen={sync_result.entries_seen} "
                f"matched={sync_result.matched} finalized={sync_result.finalized} error={sync_result.error!r}"
            )
        except Exception as exc:  # noqa: BLE001 -- one bad historical window must not abort the whole batch
            db.rollback()
            result.errors.append(f"{window.display_name}: {exc}")
            logger.exception("Historical backfill failed for window %s", window.display_name)

    return result


def resume_incomplete_historical_backfills(db: Session) -> list[SyncResult]:
    """Finds any historical-archive tournament that got tracked (via
    track_tournament) but never finished syncing -- e.g. the script/network
    connection was interrupted mid-run -- and finishes each one via
    sync_tournament(..., skip_finalize=True), the same safe no-dividend
    path a fresh backfill uses.

    This matters because nothing else will ever pick these back up:
    find_historical_backfill_candidates excludes anything with an existing
    OsirionTournamentMapping (which track_tournament already created), and
    is_historical_archive rows are deliberately excluded from every other
    sync path (sync_all_tracked, reconcile_stale_tournaments.py -- see
    their own comments) specifically so they can never be finalized with a
    real dividend payout. Without this function, an interrupted historical
    tournament would be permanently stuck non-finalized -- not lost or
    corrupted (each already-fetched leaderboard page commits as it goes),
    just never revisited by anything.

    Safe and cheap to call every run even when there's nothing to resume:
    sync_tournament always re-walks a tournament's leaderboard from page 0
    (upsert_placement_result is idempotent, so reprocessing already-seen
    pages is a harmless no-op), so this just finishes the job."""
    mappings = (
        db.query(OsirionTournamentMapping)
        .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
        .filter(Tournament.is_historical_archive.is_(True))
        .filter(Tournament.status != TournamentStatus.FINALIZED)
        .all()
    )
    results: list[SyncResult] = []
    for mapping in mappings:
        try:
            results.append(sync_tournament(db, mapping, skip_finalize=True))
        except Exception as exc:  # noqa: BLE001 -- defense in depth, same reasoning as sync_all_tracked
            db.rollback()
            logger.exception("Resuming incomplete historical backfill failed for mapping %s", mapping.id)
            results.append(SyncResult(tournament_id=mapping.tournament_id, error=f"unexpected error: {exc}"))
    return results


def sync_all_tracked(db: Session) -> list[SyncResult]:
    # Excludes is_historical_archive rows on purpose -- this is the
    # background loop's own automatic sync pass (see app/main.py's
    # _osirion_sync_loop, runs every 45s), and it always calls plain
    # sync_tournament() with skip_finalize defaulting to False. A
    # backfilled historical tournament sits non-finalized (same as a
    # normal in-progress one) for however long its own sync takes to walk
    # the full leaderboard -- without this filter, THIS loop could race in
    # during that window and finish syncing it via the normal path,
    # calling finalize_tournament() and creating real DividendPayout rows
    # for an already-decided historical result. Only
    # backfill_historical_tournaments (via sync_tournament(...,
    # skip_finalize=True)) is ever allowed to finish syncing one of these.
    mappings = (
        db.query(OsirionTournamentMapping)
        .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
        .filter(Tournament.status != TournamentStatus.FINALIZED)
        .filter(Tournament.is_historical_archive.is_(False))
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


# --- Announced-but-not-yet-tracked events (calendar completeness) ---------------------------------------------------

_ANNOUNCED_CACHE: dict = {"t": 0.0, "rows": []}
ANNOUNCED_CACHE_SECONDS = 15 * 60


def list_announced_events(db: Session, force: bool = False) -> list[dict]:
    """Every FUTURE event Osirion has announced that qualifies for this platform but isn't tracked as a Tournament yet.

    The auto-tracker only creates a Tournament once a window shows a real cash payout table, and Osirion often publishes
    that after the event is announced -- so for a while an announced Finals exists on Osirion but not in our calendar
    (the calendar then looked empty between seasons). This lists those so the calendar can show them as "announced"
    immediately. Same qualification rules as auto-tracking (no Zero Build, classified into a tier, in the NAC/EU scope,
    the once-per-quarter FNCS Finals rule), minus the cash-payout requirement. One row per event, preferring its
    cash-paying window and otherwise its latest window (the Finals come last). Cached for 15 minutes so the public
    calendar never hammers Osirion; any Osirion error returns whatever was cached."""
    import time as _time

    now_m = _time.monotonic()
    if not force and _ANNOUNCED_CACHE["rows"] is not None and _ANNOUNCED_CACHE["t"] and now_m - _ANNOUNCED_CACHE["t"] < ANNOUNCED_CACHE_SECONDS:
        return _ANNOUNCED_CACHE["rows"]
    try:
        windows = list_available_windows()
    except Exception:  # noqa: BLE001 -- no API key / Osirion down: calendar still works from tracked tournaments
        _ANNOUNCED_CACHE["t"] = now_m
        return _ANNOUNCED_CACHE["rows"] or []

    from app.services import economic_params_service

    now = datetime.now(timezone.utc)
    tracked_keys = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in db.query(OsirionTournamentMapping).all()}
    by_event: dict[str, list[AvailableWindow]] = {}
    for w in windows:
        if w.is_zero_build:
            continue
        when = w.end_time or w.begin_time
        if when is None or when <= now:
            continue  # already over (or undated): not an announcement
        by_event.setdefault(w.event_id, []).append(w)

    # Events that already have ANY window tracked are in the calendar as real tournaments.
    tracked_events = {w.event_id for w in windows if (w.leaderboard_event_id, w.leaderboard_event_window_id) in tracked_keys}

    rows: list[dict] = []
    for event_id, group in by_event.items():
        if event_id in tracked_events:
            continue
        cash = [w for w in group if w.has_cash_payout]
        window = max(cash, key=lambda w: w.top_cash_amount) if cash else max(group, key=lambda w: w.begin_time or w.end_time)
        tournament_type = tournament_classification_service.classify(db, window.classification_text)
        if tournament_type is None or not _in_tracking_region_scope(tournament_type, window.regions):
            continue
        region_key = _region_key(window.regions)
        if tournament_type == TournamentType.FNCS_FINALS:
            quarter_key = _season_quarter_key(window.begin_time or now)
            if _has_tournament_in_quarter_and_region(db, TournamentType.GLOBAL_CHAMPIONSHIP, quarter_key, region_key) or _has_tournament_in_quarter_and_region(
                db, TournamentType.FNCS_FINALS, quarter_key, region_key
            ):
                continue
        region = window.regions[0] if len(window.regions) == 1 else None
        pool = economic_params_service.get_fixed_tournament_pool(db, tournament_type)
        if pool is not None:
            pool = pool * economic_params_service.get_region_multiplier(db, region)
        rows.append(
            {
                "event_id": event_id,
                "name": window.display_name,
                "tournament_type": tournament_type,
                "region": region,
                "start_time": window.begin_time,
                "end_time": window.end_time,
                "total_dividend_pool": pool,
                "finals_confirmed": bool(window.has_cash_payout),
            }
        )
    rows.sort(key=lambda r: (r["start_time"] is None, r["start_time"] or now))
    _ANNOUNCED_CACHE["t"] = now_m
    _ANNOUNCED_CACHE["rows"] = rows
    return rows
