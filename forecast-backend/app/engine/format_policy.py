"""
Tournament FORMAT -> dividend pool + payout shape. Pure functions (no DB, no network).

Product rules (Nov 2026), for every tracked Battle Royale (build) cup that is not a Victory cup / Performance Evaluation:

  * FNCS events                                  -> the FNCS pool (online) / Global pool (LAN) -- the tier decides, unchanged.
  * Final SET LOBBY (not FNCS)                   -> Cash Cup pool        ($300,000)
  * OPEN round that pays cash                    -> qualifier pool       ($150,000)
  * SET LOBBY that is a later round (after the 1st round of a multi-round event), cash or not
                                                 -> qualifier pool       ($150,000)
  * OPEN round with no cash (only advancement)   -> no payout; browse-only, never a tournament
  * First-round set lobby with no cash           -> not tracked

The payout SHAPE follows the scoring rules Osirion publishes for the window (scoreLocations[].scoringRules):
  * 'wins'      -- points only for winning a game (no elimination points, no placement points below 1st): the pool is paid
                   per game won, exactly like a Performance Evaluation cup.
  * 'placement' -- everything else: the pool is split by final placement through the placement curve.

The decision is stored on the tournament (`format_rules`) when it is tracked, so every pool lookup reads one record.
"""
from __future__ import annotations

from typing import Any

POOL_FINAL = "dividend.cash_cup_pool"
POOL_ROUND = "dividend.qualifier_pool"

LOBBY_SET = "set"
LOBBY_OPEN = "open"
LOBBY_UNKNOWN = "unknown"

SCORING_WINS = "wins"
SCORING_PLACEMENT = "placement"


def scoring_kind(score_location: dict | None) -> str:
    """'wins' when the window only rewards winning games; otherwise 'placement'. No scoring rules published -> 'placement'."""
    rules = (score_location or {}).get("scoringRules") or []
    if not rules:
        return SCORING_PLACEMENT
    saw_win_points = False
    for rule in rules:
        stat = str(rule.get("trackedStat") or "").upper()
        tiers = rule.get("rewardTiers") or []
        if "ELIM" in stat:
            if any(_num(t.get("pointsEarned")) > 0 for t in tiers):
                return SCORING_PLACEMENT
        elif "PLACEMENT" in stat:
            for t in tiers:
                pts = _num(t.get("pointsEarned"))
                if pts <= 0:
                    continue
                if _num(t.get("keyValue")) > 1:
                    return SCORING_PLACEMENT  # points for places below 1st: a normal placement-scored event
                saw_win_points = True
    return SCORING_WINS if saw_win_points else SCORING_PLACEMENT


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def lobby_label(set_lobby: bool | None) -> str:
    return LOBBY_UNKNOWN if set_lobby is None else (LOBBY_SET if set_lobby else LOBBY_OPEN)


def decide(*, lobby: str, has_cash: bool, stage_index: int, scoring: str = SCORING_PLACEMENT) -> dict | None:
    """Format record for a generic (non-FNCS) window, or None = do not track.
    `stage_index` is the window's position (0 = first) among the windows of its edition, in time order."""
    if lobby == LOBBY_OPEN:
        if not has_cash:
            return None
        return _rec(lobby, "round", True, POOL_ROUND, scoring, False)
    if lobby == LOBBY_SET:
        if has_cash:
            # one set-lobby window is kept per edition (the best-paying), and that is its final
            return _rec(lobby, "final", True, POOL_FINAL, scoring, False)
        if stage_index >= 1:
            return _rec(lobby, "round", False, POOL_ROUND, scoring, False)
        return None
    # lobby not known yet (window has not started): list it with the cautious pool; refreshed once its field is visible
    if has_cash:
        return _rec(lobby, "unknown", True, POOL_ROUND, scoring, True)
    return None


def _rec(lobby: str, stage: str, cash: bool, pool_param: str | None, scoring: str, provisional: bool) -> dict:
    return {"lobby": lobby, "stage": stage, "cash": cash, "pool_param": pool_param, "scoring": scoring, "provisional": provisional}


def tier_record(*, lobby: str, has_cash: bool, scoring: str = SCORING_PLACEMENT, stage: str = "final") -> dict:
    """Format record for an FNCS / Global / Major event: the tier's own pool applies (pool_param None)."""
    return _rec(lobby, stage, has_cash, None, scoring, False)


def describe(rules: dict | None) -> str:
    if not rules:
        return "tier default"
    parts = [f"{rules.get('lobby', '?')} lobby", rules.get("stage", "?"), "cash" if rules.get("cash") else "no cash", f"{rules.get('scoring', 'placement')}-scored"]
    if rules.get("provisional"):
        parts.append("provisional")
    return ", ".join(parts)
