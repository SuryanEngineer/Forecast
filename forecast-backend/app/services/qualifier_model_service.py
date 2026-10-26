"""
What the earlier rounds of a Finals event tell us about who will be in it and how they'll place -- for the bots.

Learned from history (not hard-coded):
  * fit_model() looks at every FINALIZED event we hold both rounds and results for, and learns
      - how a player's qualifier strength maps to their Finals strength (a line, shrunk toward a prior), and
      - how often each qualifier-strength bucket actually makes the Finals.
    With little data it leans on the priors in app/engine/qualifier_math.py; as qualifier data accumulates it leans on the data.

Applied to upcoming events (build_views):
  * who is already in the Finals field / eliminated / still pending,
  * P(makes the Finals): exact when the round's advancement cutoff is known, learned rate otherwise,
  * expected Finals placement -> expected dividend, using the player's own qualifier strength blended with how strong their
    TEAM is on paper (the qualifier teammates' career results -- duos/trios finish together),
  * expressed as `perf_ratio` = expected dividend from this event / what this player's events typically pay.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.dividend_calculator import placement_payout_fraction
from app.engine.qualifier_math import (
    DEFAULT_QUALIFY_PRIOR,
    expected_strength,
    final_strength,
    fit_line,
    p_qualify,
    placement_from_strength,
    qual_score,
    qualify_rates,
    weighted_qual,
)
from app.models.qualifier import QualifierResult, QualifierWindow
from app.models.tournament import PlacementResult, Tournament, TournamentEntrant, TournamentStatus
from app.services import economic_params_service

logger = logging.getLogger("forecast.bots")

_MODEL_TTL = 30 * 60
DEFAULT_FIELD = 100
FIELD_KNOWN_MIN = 20  # this many placements means the Finals field is known/under way


@dataclass
class QualModel:
    a: float = 0.30
    b: float = 0.45
    resid_sd: float = 0.28
    n_pairs: int = 0
    rates: list = field(default_factory=lambda: list(DEFAULT_QUALIFY_PRIOR))
    n_players_events: int = 0
    typical_field: int = DEFAULT_FIELD


@dataclass
class QualifierView:
    tournament_id: uuid.UUID
    event_start: datetime | None
    status: str                 # qualified | eliminated | likely | unlikely | pending
    p_qualify: float
    perf_ratio: float           # expected dividend from this event / typical for this player (0..3)
    q: float                    # qualifier strength 0..1
    n_rounds: int
    expected_placement: int | None
    uncertainty: float          # 0..1 -- how unsure this estimate is (few rounds, event far away, little training data)
    teammates: list = field(default_factory=list)
    detail: str = ""


_model_cache: tuple[float, QualModel] | None = None


def clear_cache() -> None:
    global _model_cache
    _model_cache = None


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _round_strengths(db: Session, tournament_ids: list[uuid.UUID]):
    """{(tournament_id, player_id): [(stage, q, rank, window)]} plus {tournament_id: [windows]}."""
    windows = db.query(QualifierWindow).filter(QualifierWindow.tournament_id.in_(tournament_ids)).all() if tournament_ids else []
    by_window = {w.id: w for w in windows}
    by_t: dict[uuid.UUID, list[QualifierWindow]] = defaultdict(list)
    for w in windows:
        by_t[w.tournament_id].append(w)
    rounds: dict[tuple, list] = defaultdict(list)
    teams: dict[tuple, set] = defaultdict(set)
    if windows:
        for r in db.query(QualifierResult).filter(QualifierResult.window_id.in_(list(by_window.keys()))).all():
            w = by_window.get(r.window_id)
            if w is None:
                continue
            rounds[(r.tournament_id, r.player_id)].append((w.stage_index, qual_score(r.rank, w.field_estimate), r.rank, w))
            for t in r.teammate_player_ids or []:
                try:
                    teams[(r.tournament_id, r.player_id)].add(uuid.UUID(str(t)))
                except ValueError:
                    pass
    return rounds, by_t, teams


def fit_model(db: Session, force: bool = False) -> QualModel:
    """Learns the qualifier -> Finals relationship from finalized events. Cached for 30 minutes."""
    global _model_cache
    now = time.monotonic()
    if not force and _model_cache is not None and now - _model_cache[0] < _MODEL_TTL:
        return _model_cache[1]
    model = QualModel()
    try:
        done_ids = [
            tid for (tid,) in db.query(QualifierWindow.tournament_id).join(Tournament, Tournament.id == QualifierWindow.tournament_id)
            .filter(Tournament.status == TournamentStatus.FINALIZED).distinct().all()
        ]
        if done_ids:
            rounds, _by_t, _teams = _round_strengths(db, done_ids)
            placements: dict[tuple, int] = {}
            field_size: dict[uuid.UUID, int] = {}
            for tid, pid, plc in db.query(PlacementResult.tournament_id, PlacementResult.player_id, PlacementResult.placement).filter(
                PlacementResult.tournament_id.in_(done_ids)
            ).all():
                placements[(tid, pid)] = plc
            for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).filter(
                PlacementResult.tournament_id.in_(done_ids)
            ).group_by(PlacementResult.tournament_id).all():
                field_size[tid] = n
            pairs: list[tuple[float, float]] = []
            rows: list[tuple[float, bool]] = []
            for (tid, pid), rs in rounds.items():
                if field_size.get(tid, 0) < FIELD_KNOWN_MIN:
                    continue  # the Finals field isn't complete enough to say who qualified
                q = weighted_qual([(st, qv) for st, qv, _r, _w in rs])
                if q is None:
                    continue
                plc = placements.get((tid, pid))
                rows.append((q, plc is not None))
                if plc is not None:
                    pairs.append((q, final_strength(plc, field_size[tid])))
            model.a, model.b, model.resid_sd, model.n_pairs = fit_line(pairs)
            model.rates = qualify_rates(rows)
            model.n_players_events = len(rows)
            sizes = sorted(field_size.values())
            if sizes:
                model.typical_field = max(DEFAULT_FIELD // 2, sizes[len(sizes) // 2])
    except Exception:  # noqa: BLE001 -- the bots must keep trading on priors if this fails
        logger.exception("Qualifier model fit failed; using priors")
    _model_cache = (now, model)
    return model


def build_views(
    db: Session,
    player_ids: list[uuid.UUID],
    career_fraction: dict[uuid.UUID, float],
    career_strength: dict[uuid.UUID, float],
) -> dict[uuid.UUID, QualifierView]:
    """One QualifierView per roster player that has earlier-round results for an upcoming / in-progress Finals.
    If a player has more than one such event, the soonest wins."""
    out: dict[uuid.UUID, QualifierView] = {}
    if not player_ids or not settings.QUALIFIER_SYNC_ENABLED:
        return out
    now = datetime.now(timezone.utc)
    try:
        tournaments = (
            db.query(Tournament)
            .filter(
                Tournament.status != TournamentStatus.FINALIZED, Tournament.is_historical_archive.is_(False),
                Tournament.start_time.isnot(None), Tournament.start_time >= now - timedelta(days=3),
                Tournament.start_time <= now + timedelta(days=30),
            ).all()
        )
        if not tournaments:
            return out
        t_by_id = {t.id: t for t in tournaments}
        tids = list(t_by_id.keys())
        rounds, windows_by_t, teams = _round_strengths(db, tids)
        if not rounds:
            return out
        model = fit_model(db)
        curve = economic_params_service.get_placement_curve(db)

        placed: dict[uuid.UUID, set] = defaultdict(set)
        for tid, pid in db.query(PlacementResult.tournament_id, PlacementResult.player_id).filter(PlacementResult.tournament_id.in_(tids)).all():
            placed[tid].add(pid)
        entrants: dict[uuid.UUID, set] = defaultdict(set)
        for tid, pid in db.query(TournamentEntrant.tournament_id, TournamentEntrant.player_id).filter(TournamentEntrant.tournament_id.in_(tids)).all():
            entrants[tid].add(pid)

        wanted = set(player_ids)
        for (tid, pid), rs in rounds.items():
            if pid not in wanted:
                continue
            t = t_by_id.get(tid)
            if t is None:
                continue
            start = _aware(t.start_time)
            days_out = (start - now).total_seconds() / 86400.0 if start else 0.0
            wins = sorted(windows_by_t.get(tid, []), key=lambda w: w.stage_index)
            last = wins[-1] if wins else None
            q = weighted_qual([(st, qv) for st, qv, _r, _w in rs])
            if q is None:
                continue
            by_stage = {st: (qv, rank, w) for st, qv, rank, w in rs}
            field_known = len(placed[tid]) >= FIELD_KNOWN_MIN
            in_field = pid in placed[tid] or pid in entrants[tid]

            status, p_q, detail = "pending", p_qualify(q, model.rates), "rounds still being played"
            if in_field:
                status, p_q, detail = "qualified", 1.0, "in the Finals field"
            elif field_known:
                status, p_q, detail = "eliminated", 0.02, "Finals field is set and they are not in it"
            else:
                # Did they miss an advancement cutoff in a completed round?
                missed = next(
                    ((st, rank, w) for st, (qv, rank, w) in sorted(by_stage.items())
                     if w.is_complete and w.advance_cutoff and rank > w.advance_cutoff and w is not last), None)
                if last is not None and last.is_complete:
                    mine = by_stage.get(last.stage_index)
                    if mine is not None and last.advance_cutoff:
                        ok = mine[1] <= last.advance_cutoff
                        status, p_q = ("likely", 0.95) if ok else ("eliminated", 0.03)
                        detail = f"last round rank {mine[1]} vs cutoff {last.advance_cutoff}"
                    elif mine is None and not last.capped and rs:
                        status, p_q, detail = "eliminated", 0.04, "did not appear in the last round"
                if missed is not None and status == "pending":
                    status, p_q = "eliminated", 0.03
                    detail = f"missed the round-{missed[0]} cutoff ({missed[1]} > {missed[2].advance_cutoff})"
                if status == "pending":
                    status = "likely" if p_q >= 0.6 else "unlikely" if p_q <= 0.25 else "pending"

            # Expected dividend if they make it: their qualifier strength + their team's strength on paper.
            mates = sorted(teams.get((tid, pid), set()), key=str)
            pool = [career_strength.get(m) for m in mates if career_strength.get(m) is not None]
            own = career_strength.get(pid)
            if own is not None:
                pool.append(own)
            team_prior = sum(pool) / len(pool) if pool else None
            s_hat = expected_strength(model.a, model.b, q, team_prior, n_rounds=len(rs))
            field_n = max(len(placed[tid]), model.typical_field)
            plc_hat = placement_from_strength(s_hat, field_n)
            frac_hat = float(placement_payout_fraction(plc_hat, field_n, curve))
            base = career_fraction.get(pid)
            ratio_if_q = max(0.2, min(3.0, frac_hat / base)) if base and base > 0 else 1.0
            perf = max(0.0, min(3.0, p_q * ratio_if_q))

            data_conf = min(1.0, model.n_pairs / 150.0)
            unc = max(0.1, min(1.0, 0.85 - 0.12 * (len(rs) - 1) - 0.25 * data_conf + (0.1 if days_out > 7 else 0.0) - (0.25 if status in ("qualified", "eliminated") else 0.0)))
            view = QualifierView(
                tournament_id=tid, event_start=start, status=status, p_qualify=p_q, perf_ratio=perf, q=q, n_rounds=len(rs),
                expected_placement=plc_hat if p_q >= 0.5 else None, uncertainty=unc, teammates=mates, detail=detail,
            )
            prev = out.get(pid)
            if prev is None or (view.event_start and prev.event_start and view.event_start < prev.event_start):
                out[pid] = view
    except Exception:  # noqa: BLE001
        logger.exception("Qualifier views failed; bots fall back to results-only valuation")
        return {}
    return out
