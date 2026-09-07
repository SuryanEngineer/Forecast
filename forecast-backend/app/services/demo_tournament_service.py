"""
Demo-mode-only: randomized tournament results, so the demo market keeps
producing real activity (price-relevant dividend payouts) on its own,
without an admin manually entering placements. This reuses the exact
same tournament/dividend service functions the real admin-entry flow
uses (app/services/tournament_service.py, app/services/dividend_service.py)
-- the only thing "fake" here is where the placements come from
(shuffled at random instead of a human typing in real results).

Never imported or used outside DEMO_MODE -- see app/main.py's lifespan.
"""
from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.player import Player
from app.models.tournament import TournamentType
from app.services import tournament_service

logger = logging.getLogger("forecast.demo_tournaments")

# Weighted like the real economy's chapter cadence (lots of small Cash
# Cups, a handful of FNCS, a rare Global Championship) rather than
# uniformly random, so the demo "feels" like the real tournament mix.
_TOURNAMENT_TYPE_WEIGHTS: list[tuple[TournamentType, int]] = [
    (TournamentType.CASH_CUP, 12),
    (TournamentType.FNCS_QUALIFIER, 3),
    (TournamentType.FNCS_FINALS, 2),
    (TournamentType.GLOBAL_CHAMPIONSHIP, 1),
]

_TOURNAMENT_NAME_BY_TYPE: dict[TournamentType, str] = {
    TournamentType.CASH_CUP: "Demo Cash Cup",
    TournamentType.FNCS_QUALIFIER: "Demo FNCS Qualifier",
    TournamentType.FNCS_FINALS: "Demo FNCS Finals",
    TournamentType.GLOBAL_CHAMPIONSHIP: "Demo Global Championship",
}


def _pick_tournament_type(rng: random.Random) -> TournamentType:
    types, weights = zip(*_TOURNAMENT_TYPE_WEIGHTS)
    return rng.choices(types, weights=weights, k=1)[0]


def _weighted_placement_order(rng: random.Random, players: list[Player]) -> list[Player]:
    """Skill-weighted placement draw (Plackett-Luce style): repeatedly
    draws the next finisher from whoever's left via a weighted lottery
    keyed off power_rating, then removes them and draws again for the
    next placement. Higher-rated players are more likely to place near
    the top, but never guaranteed to -- a rating-97 player can still
    occasionally place last; that's a feature (real upsets happen), not a
    bug. Before this, demo tournaments used a pure `rng.shuffle`, so
    power_rating had no bearing at all on simulated results even though
    it now drives ipo_price and bot fair-value pricing (see
    player_service.ipo_price_for_rating and bot_trading_service.py's
    fair-value anchoring) -- simulated placements were silently
    disconnected from the skill signal everything else respects. Ported
    from the standalone browser build's weightedGroupPlacementOrder
    (engine/demoTournamentService.ts): weight = 2^(power_rating/15)."""
    pool = list(players)
    order: list[Player] = []
    while pool:
        weights = [2 ** (p.power_rating / 15) for p in pool]
        total = sum(weights)
        r = rng.uniform(0, total)
        upto = 0.0
        chosen_idx = len(pool) - 1
        for i, w in enumerate(weights):
            upto += w
            if upto >= r:
                chosen_idx = i
                break
        order.append(pool.pop(chosen_idx))
    return order


def run_random_tournament(db: Session, rng: random.Random) -> dict:
    """Runs one full randomized tournament cycle: pick a subset of active
    players, draw them into placements weighted by skill, finalize (which
    creates + dispatches dividend payouts exactly like a real admin-
    entered tournament would). Returns a small summary dict for logging."""
    players = db.query(Player).filter(Player.is_active.is_(True)).all()
    if len(players) < 2:
        return {"skipped": "fewer than 2 active players -- nothing to run a tournament with"}

    field_size = min(len(players), rng.randint(6, 16))
    field = _weighted_placement_order(rng, rng.sample(players, field_size))

    tournament_type = _pick_tournament_type(rng)
    tournament = tournament_service.create_tournament(
        db,
        name=f"{_TOURNAMENT_NAME_BY_TYPE[tournament_type]} #{rng.randint(1000, 9999)}",
        tournament_type=tournament_type,
        # No prize_pool needed -- Cash Cup/FNCS/Global all use the fixed
        # synthetic pool from economic_params_service.py regardless (see
        # dividend_service.create_payout_for_placement).
    )

    for placement, player in enumerate(field, start=1):
        tournament_service.upsert_placement_result(
            db,
            tournament_id=tournament.id,
            player_id=player.id,
            placement=placement,
            eliminations=rng.randint(0, 12),
        )

    payouts = tournament_service.finalize_tournament(db, tournament.id)
    db.commit()

    return {
        "tournament_id": str(tournament.id),
        "tournament_type": tournament_type.value,
        "field_size": field_size,
        "payouts_created": len(payouts),
    }


def _run_one_demo_tournament(rng: random.Random) -> dict:
    db = SessionLocal()
    try:
        return run_random_tournament(db, rng)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def demo_tournament_loop() -> None:
    """Runs for the lifetime of the process, alongside the bot-tick loop
    (see app/main.py's lifespan). A longer initial delay than the bot
    loop's, so a fresh demo has some organic trading activity before the
    first randomized tournament fires."""
    rng = random.Random()
    await asyncio.sleep(20)
    while True:
        try:
            result = await asyncio.to_thread(_run_one_demo_tournament, rng)
            logger.info("Demo tournament: %s", result)
        except Exception:
            logger.exception("Demo tournament run failed -- will retry next interval.")
        await asyncio.sleep(settings.DEMO_TOURNAMENT_INTERVAL_SECONDS)
