"""
Admin-only endpoints: the "manual admin entry tool" the roadmap calls for
as the v1 way to get tournament results into the system (see
app/services/tournament_service.py's module docstring for the full
rationale, and README_SETUP.md for how to create your first admin user).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import random

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.bot import BotProfile
from app.models.user import User
from app.schemas.auction import AuctionRoundResponse
from app.schemas.bot import BotSeedResponse, BotTickResponse
from app.schemas.dividend import DividendPayoutResponse
from app.schemas.economic_params import (
    DividendCurveEntryResponse,
    DividendCurveEntryUpdateRequest,
    PlatformParameterResponse,
    PlatformParameterUpdateRequest,
    RegionMultiplierResponse,
    RegionMultiplierUpdateRequest,
    TournamentClassificationRuleCreateRequest,
    TournamentClassificationRuleResponse,
    TournamentClassificationRuleUpdateRequest,
)
from app.schemas.osirion import (
    AutoTrackResultResponse,
    AvailableWindowResponse,
    SyncResultResponse,
    TrackedTournamentResponse,
    TrackTournamentRequest,
)
from app.schemas.tournament import PlacementResultRequest, PlacementResultResponse, TournamentCreateRequest, TournamentResponse
from app.schemas.treasury import TreasuryInstrumentResponse, TreasuryRateUpdateRequest
from app.services import (
    auction_service,
    bot_trading_service,
    economic_params_service,
    osirion_service,
    tournament_classification_service,
    tournament_service,
    treasury_service,
)
from app.integrations.osirion_client import OsirionApiError
from app.models.osirion import OsirionTournamentMapping
from app.models.tournament import Tournament
from app.models.tournament_classification import RegionMultiplier
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/admin", tags=["admin"])


def _to_http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/tournaments", response_model=TournamentResponse, status_code=status.HTTP_201_CREATED)
def create_tournament(payload: TournamentCreateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> TournamentResponse:
    tournament = tournament_service.create_tournament(
        db,
        name=payload.name,
        tournament_type=payload.tournament_type,
        prize_pool=payload.prize_pool,
        region=payload.region,
        start_time=payload.start_time,
        end_time=payload.end_time,
        created_by_admin_id=admin.id,
    )
    db.commit()
    return tournament


@router.post("/tournaments/{tournament_id}/results", response_model=PlacementResultResponse, status_code=status.HTTP_201_CREATED)
def submit_placement_result(
    tournament_id: uuid.UUID,
    payload: PlacementResultRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> PlacementResultResponse:
    """Enter (or correct) one player's placement in a tournament. Safe to
    call repeatedly for the same player -- it upserts. Does NOT trigger
    dividends by itself; call the /finalize endpoint once every result
    for the tournament has been entered."""
    try:
        result = tournament_service.upsert_placement_result(
            db,
            tournament_id=tournament_id,
            player_id=payload.player_id,
            placement=payload.placement,
            points=payload.points,
            prize_won=payload.prize_won,
            eliminations=payload.eliminations,
            raw_notes=payload.raw_notes,
            entered_by_admin_id=admin.id,
        )
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return result


@router.post("/tournaments/{tournament_id}/finalize", response_model=list[DividendPayoutResponse])
def finalize_tournament(tournament_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[DividendPayoutResponse]:
    """Lock in every placement result entered so far and queue dividend
    payouts (processed in the background -- see app/jobs/tasks.py). Safe
    to call more than once; already-created payouts are not duplicated
    or re-enqueued."""
    try:
        payouts = tournament_service.finalize_tournament(db, tournament_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return payouts


# --- Osirion live tournament data (see app/services/osirion_service.py) ---
# Three-step admin flow: (1) browse what's currently trackable, (2) pick
# one window and start tracking it -- creates the internal Tournament for
# you, (3) either wait for the automatic background sync (every
# OSIRION_SYNC_INTERVAL_SECONDS -- see app/main.py) or trigger one
# immediately here for testing.

@router.get("/osirion/available-tournaments", response_model=list[AvailableWindowResponse])
def list_available_osirion_tournaments(
    region: str | None = None,
    include_historic_data: bool = False,
    admin: User = Depends(get_current_admin),
) -> list[AvailableWindowResponse]:
    try:
        windows = osirion_service.list_available_windows(region=region, include_historic_data=include_historic_data)
    except OsirionApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [AvailableWindowResponse(**vars(w)) for w in windows]


@router.post("/osirion/track-tournament", response_model=TrackedTournamentResponse, status_code=status.HTTP_201_CREATED)
def track_osirion_tournament(
    payload: TrackTournamentRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> TrackedTournamentResponse:
    """Creates a new internal Tournament AND starts tracking it against
    the given Osirion window, in one call -- copy the window fields
    straight from GET /osirion/available-tournaments."""
    window = osirion_service.AvailableWindow(
        event_id=payload.event_id,
        event_window_id=payload.event_window_id,
        round=payload.round,
        leaderboard_event_id=payload.leaderboard_event_id,
        leaderboard_event_window_id=payload.leaderboard_event_window_id,
        is_main=payload.is_main,
        begin_time=payload.begin_time,
        end_time=payload.end_time,
        display_name=payload.display_name,
        regions=payload.regions,
    )
    mapping = osirion_service.track_tournament(
        db,
        name=payload.name,
        tournament_type=payload.tournament_type,
        region=payload.region,
        window=window,
        created_by_admin_id=admin.id,
    )
    tournament = db.get(Tournament, mapping.tournament_id)
    return TrackedTournamentResponse(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        tournament_status=tournament.status.value,
        osirion_display_name=mapping.osirion_display_name,
        window_begin_time=mapping.window_begin_time,
        window_end_time=mapping.window_end_time,
        last_synced_at=mapping.last_synced_at,
    )


@router.get("/osirion/tracked-tournaments", response_model=list[TrackedTournamentResponse])
def list_tracked_osirion_tournaments(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[TrackedTournamentResponse]:
    rows = (
        db.query(OsirionTournamentMapping, Tournament)
        .join(Tournament, Tournament.id == OsirionTournamentMapping.tournament_id)
        .order_by(OsirionTournamentMapping.created_at.desc())
        .all()
    )
    return [
        TrackedTournamentResponse(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            tournament_status=tournament.status.value,
            osirion_display_name=mapping.osirion_display_name,
            window_begin_time=mapping.window_begin_time,
            window_end_time=mapping.window_end_time,
            last_synced_at=mapping.last_synced_at,
        )
        for mapping, tournament in rows
    ]


@router.post("/osirion/tournaments/{tournament_id}/sync-now", response_model=SyncResultResponse)
def sync_osirion_tournament_now(
    tournament_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> SyncResultResponse:
    mapping = (
        db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == tournament_id).one_or_none()
    )
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This tournament isn't tracked via Osirion")
    result = osirion_service.sync_tournament(db, mapping)
    return SyncResultResponse(
        tournament_id=result.tournament_id,
        entries_seen=result.entries_seen,
        matched=result.matched,
        unmatched_usernames=result.unmatched_usernames,
        finalized=result.finalized,
        error=result.error,
    )


@router.post("/osirion/auto-track-now", response_model=AutoTrackResultResponse)
def auto_track_osirion_tournaments_now(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> AutoTrackResultResponse:
    """Runs the same auto-classification/auto-tracking pass the
    background loop already runs every OSIRION_SYNC_INTERVAL_SECONDS (see
    app/main.py), immediately -- useful right after changing a
    classification rule, without waiting for the next scheduled pass."""
    result = osirion_service.auto_track_new_tournaments(db)
    db.commit()
    return AutoTrackResultResponse(
        windows_seen=result.windows_seen,
        tracked=result.tracked,
        skipped_already_tracked=result.skipped_already_tracked,
        skipped_unclassified=result.skipped_unclassified,
        skipped_season_dedup=result.skipped_season_dedup,
        errors=result.errors,
    )


# --- Tournament auto-classification rules (see
# app/services/tournament_classification_service.py). Pattern is a
# case-insensitive substring match against the Osirion window's display
# name; tournament_type=null means "exclude" (never auto-track a match).
# Lower `priority` is checked first, first match wins. ---

@router.get("/osirion/classification-rules", response_model=list[TournamentClassificationRuleResponse])
def list_classification_rules(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[TournamentClassificationRuleResponse]:
    rules = tournament_classification_service.get_all_rules(db)
    db.commit()
    return rules


@router.post("/osirion/classification-rules", response_model=TournamentClassificationRuleResponse, status_code=status.HTTP_201_CREATED)
def create_classification_rule(
    payload: TournamentClassificationRuleCreateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> TournamentClassificationRuleResponse:
    rule = tournament_classification_service.create_rule(
        db,
        pattern=payload.pattern,
        tournament_type=payload.tournament_type,
        priority=payload.priority,
        is_active=payload.is_active,
        description=payload.description,
    )
    db.commit()
    return rule


@router.post("/osirion/classification-rules/{rule_id}", response_model=TournamentClassificationRuleResponse)
def update_classification_rule(
    rule_id: uuid.UUID,
    payload: TournamentClassificationRuleUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TournamentClassificationRuleResponse:
    try:
        rule = tournament_classification_service.update_rule(
            db,
            rule_id,
            pattern=payload.pattern,
            tournament_type=payload.tournament_type,
            clear_tournament_type=payload.clear_tournament_type,
            priority=payload.priority,
            is_active=payload.is_active,
            description=payload.description,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return rule


@router.delete("/osirion/classification-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_classification_rule(rule_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> None:
    try:
        tournament_classification_service.delete_rule(db, rule_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# --- Per-region dividend payout scale factor (see
# economic_params_service.get_region_multiplier) -- applied on top of a
# tournament tier's fixed pool (cash_cup_pool/fncs_pool/global_pool,
# already adjustable via /admin/economic-parameters) whenever a tracked
# tournament has exactly one region set. ---

@router.get("/region-multipliers", response_model=list[RegionMultiplierResponse])
def list_region_multipliers(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[RegionMultiplierResponse]:
    economic_params_service.get_region_multipliers(db)  # ensure defaults are seeded
    rows = db.query(RegionMultiplier).order_by(RegionMultiplier.region.asc()).all()
    db.commit()
    return rows


@router.post("/region-multipliers", response_model=RegionMultiplierResponse)
def set_region_multiplier(
    payload: RegionMultiplierUpdateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> RegionMultiplierResponse:
    row = economic_params_service.set_region_multiplier(db, payload.region, payload.multiplier)
    db.commit()
    return row


@router.post("/auctions", response_model=AuctionRoundResponse, status_code=status.HTTP_201_CREATED)
def open_auction_round(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> AuctionRoundResponse:
    """Open a new player-share IPO auction round (see
    app/services/auction_service.py for the full mechanics). Only one
    round may be open at a time -- finalize the current one first."""
    try:
        round_ = auction_service.open_round(db, admin.id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return round_


@router.post("/auctions/{round_id}/finalize", response_model=AuctionRoundResponse)
def finalize_auction_round(round_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> AuctionRoundResponse:
    """Close bidding and settle every player that received at least one
    bid: allocate shares pro-rata via exact largest-remainder
    apportionment, charge each winning bidder, and release the rest of
    their held cash. Irreversible -- there is no un-finalize."""
    try:
        round_ = auction_service.finalize_round(db, round_id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return round_


@router.post("/treasury/rate", response_model=TreasuryInstrumentResponse)
def set_treasury_rate(payload: TreasuryRateUpdateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> TreasuryInstrumentResponse:
    """Simulation lever: change the treasury instrument's going-forward
    APY (an inflation control -- see app/services/treasury_service.py)."""
    instrument = treasury_service.set_new_rate(db, payload.new_annual_rate, payload.effective_from)
    db.commit()
    return instrument


@router.get("/economic-parameters", response_model=list[PlatformParameterResponse])
def list_economic_parameters(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[PlatformParameterResponse]:
    """Every tunable economic knob the system currently uses: quick
    buy/sell slippage steepness and synthetic liquidity depth, the
    dividend platform fee, and the bot market-maker's ladder shape. See
    app/services/economic_params_service.py for what each key controls.
    Changing one here takes effect on the very next order/payout/quote
    refresh -- no code deploy needed."""
    params = economic_params_service.get_all_params(db)
    db.commit()
    return params


@router.post("/economic-parameters/{key}", response_model=PlatformParameterResponse)
def update_economic_parameter(
    key: str, payload: PlatformParameterUpdateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> PlatformParameterResponse:
    if key not in economic_params_service.DEFAULTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown parameter '{key}'. Valid keys: {sorted(economic_params_service.DEFAULTS.keys())}",
        )
    param = economic_params_service.set_param(db, key, payload.value, admin_id=admin.id)
    db.commit()
    return param


@router.post("/bots/seed", response_model=BotSeedResponse)
def seed_bots(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> BotSeedResponse:
    """Tops the bot population up to the current `bots.population_size`
    target (see app/services/bot_trading_service.py). Safe to call
    repeatedly -- never removes or duplicates existing bots. You don't
    need to call this manually in normal operation: the background tick
    loop (see app/main.py) calls it automatically every tick, this is
    here mainly so you can seed a population immediately rather than
    waiting for the first scheduled tick."""
    population_before = db.query(BotProfile).count()
    target = int(economic_params_service.get_param(db, "bots.population_size"))
    created = bot_trading_service.ensure_bot_population(db, target, random.Random())
    db.commit()
    return BotSeedResponse(population_before=population_before, created=created, population_after=population_before + created)


@router.post("/bots/tick", response_model=BotTickResponse)
def trigger_bot_tick(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> BotTickResponse:
    """Runs one bot-trading tick immediately, on top of whatever the
    background loop is already doing on its own schedule (see
    BOT_TICK_INTERVAL_SECONDS in app/core/config.py). Useful for testing
    without waiting for the next scheduled tick."""
    result = bot_trading_service.run_bot_tick(db, random.Random())
    return BotTickResponse(**result)


@router.get("/dividend-curve", response_model=list[DividendCurveEntryResponse])
def get_dividend_curve(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[DividendCurveEntryResponse]:
    """The default placement -> pool-fraction payout curve used whenever
    an admin enters a placement result without an exact `prize_won`
    amount (see app/engine/dividend_calculator.py)."""
    curve = economic_params_service.get_placement_curve(db)
    db.commit()
    return [DividendCurveEntryResponse(placement=p, pool_fraction=f) for p, f in sorted(curve.items())]


@router.post("/dividend-curve", response_model=DividendCurveEntryResponse)
def set_dividend_curve_entry(
    payload: DividendCurveEntryUpdateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> DividendCurveEntryResponse:
    entry = economic_params_service.set_placement_curve_entry(db, payload.placement, payload.pool_fraction)
    db.commit()
    return entry
