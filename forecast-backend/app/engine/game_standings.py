"""
Points and leaderboard position AFTER EACH GAME of a set-lobby (finals) tournament. Pure functions (no DB, no network).

Osirion gives each team's games (`sessionHistory`: in-game placement and eliminations per game) and the team's total points,
and publishes the event's scoring rules (`scoreLocations[].scoringRules`: placement tiers, elimination points). From those:

  1. points a team earned in each game          (the scoring rules applied to that game's placement / eliminations)
  2. running total after each game               (sum of games 1..N, by GAME NUMBER -- not by when a team's game ended)
  3. leaderboard position after each game        (teams ranked by that running total once game N is complete)

The rules' exact semantics are not documented, so every reading is TRIED and checked against the one thing that is known for
sure -- each team's real total points. A reading is only used when it reproduces (nearly) every team's total; if none does, the
progress is "not available" and the UI hides the columns rather than showing guesses.

Stored rules (a small JSON list kept on the tournament): [{"stat": "PLACEMENT_STAT_INDEX", "tiers": [[key, points, multiplicative], ...]}].
"""
from __future__ import annotations

from typing import Any, Iterable

PLACEMENT_MODES = ("best", "cumulative", "exact")
MATCH_TOLERANCE = 0.01
MIN_MATCH_SHARE = 0.9      # a reading must reproduce at least this share of the teams' totals
MIN_TEAMS_TO_JUDGE = 3


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def rules_from_score_location(score_location: dict | None) -> list[dict]:
    """The compact stored form of one score location's scoring rules ([] when none are published)."""
    out: list[dict] = []
    for rule in (score_location or {}).get("scoringRules") or []:
        stat = str(rule.get("trackedStat") or "")
        tiers = [
            [_num(t.get("keyValue")), _num(t.get("pointsEarned")), bool(t.get("multiplicative"))]
            for t in (rule.get("rewardTiers") or [])
        ]
        if stat and tiers:
            out.append({"stat": stat, "tiers": tiers})
    return out


def _kind(stat: str) -> str:
    up = stat.upper()
    if "ELIM" in up:
        return "elims"
    if "PLACEMENT" in up:
        return "placement"
    return "other"


def _placement_points(tiers: list, place: int, mode: str) -> float:
    reached = [t for t in tiers if place <= t[0]]          # tiers whose threshold this placement meets ("top N")
    if mode == "exact":
        return sum(t[1] for t in tiers if t[0] == place)
    if not reached:
        return 0.0
    if mode == "cumulative":
        return sum(t[1] for t in reached)
    return min(reached, key=lambda t: t[0])[1]              # "best": the tightest tier that still contains this placement


def _elim_points(tiers: list, elims: int) -> float:
    total = 0.0
    thresholds = []
    for key, pts, mult in tiers:
        if mult:
            total += pts * elims
        else:
            thresholds.append((key, pts))
    met = [t for t in thresholds if t[0] <= elims]
    if met:
        total += max(met, key=lambda t: t[0])[1]
    return total


def game_points(rules: list[dict], placement: int | None, elims: int | None, mode: str) -> float:
    """Points one game earned under the stored rules and a placement reading (`mode`)."""
    total = 0.0
    for rule in rules:
        kind = _kind(rule["stat"])
        if kind == "placement" and placement is not None:
            total += _placement_points(rule["tiers"], int(placement), mode)
        elif kind == "elims" and elims is not None:
            total += _elim_points(rule["tiers"], int(elims))
    return total


def choose_mode(rules: list[dict], teams: Iterable[dict]) -> str | None:
    """The placement reading that reproduces the teams' real totals, or None when none does.
    `teams`: dicts with "total" (the team's real points or None) and "games" ({game_no: (placement, elims)})."""
    judged = [t for t in teams if t.get("total") is not None and t.get("games")]
    if not rules or len(judged) < MIN_TEAMS_TO_JUDGE:
        return None
    best_mode, best_share = None, 0.0
    for mode in PLACEMENT_MODES:
        hits = 0
        for t in judged:
            got = sum(game_points(rules, p, e, mode) for p, e in t["games"].values())
            if abs(got - float(t["total"])) <= MATCH_TOLERANCE:
                hits += 1
        share = hits / len(judged)
        if share > best_share:
            best_mode, best_share = mode, share
    return best_mode if best_share >= MIN_MATCH_SHARE else None


def build_progress(per_game_points: dict, finals: dict, complete: dict, n_games: int) -> dict:
    """{team_key: {game_no: (points_earned_in_game, running_total, position)}}.

    per_game_points: {team_key: {game_no: points}}; finals: {team_key: final/current placement} (breaks ties);
    complete: {game_no: bool}. Running totals always add up games 1..N by number. A position is given only once game N is
    complete (it has a winner), so it never reflects a half-played game; an incomplete game gets no entry at all."""
    keys = list(per_game_points)
    running = {k: 0.0 for k in keys}
    out: dict = {k: {} for k in keys}
    for g in range(1, n_games + 1):
        for k in keys:
            running[k] += per_game_points[k].get(g, 0.0)
        if not complete.get(g):
            continue
        ranked = sorted(keys, key=lambda k: (-running[k], finals.get(k, 10**9), str(k)))
        for pos, k in enumerate(ranked, start=1):
            out[k][g] = (per_game_points[k].get(g, 0.0), round(running[k], 4), pos)
    return out
