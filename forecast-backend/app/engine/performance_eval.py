"""
Performance Evaluation cups: dividends per game WON.

A Performance Evaluation cup is a set-lobby event (40 / 80 / 100 players). Instead of paying by final placement it
pays a fixed pool per game won:

    pool for the cup        = $300,000                       (dividend.performance_eval_pool)
    one game win is worth   = pool x 1/4 = $75,000           (dividend.performance_eval_win_share)
    split across the team   = $75,000 / team size            (a trio's win = $25,000 per player)

Each member of a winning team gets that amount as THEIR dividend pool, which is then split among the people who held
that player's shares when the cup started (the normal record-date rule, see dividend_service.process_payout). A player
who wins two games gets two such amounts; a player who wins none gets nothing.

Pure functions only (no database), so the rules are unit-tested on their own (tests/test_engine_pure_logic.py).
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

CENT = Decimal("0.01")

# Osirion's per-game stat keys are not stable across seasons: try each candidate (same list the games endpoint uses).
PLACEMENT_KEYS = ("PLACEMENT_STAT_INDEX", "PLACEMENT", "placement", "Placement")

# Lobby sizes: 100 / 80 / 40 players, and trios make 80 come out as 78 or 79. Anything up to this many players counts
# as a normal Performance Evaluation lobby (a little slack over 100); a much bigger field is an open event, not a set lobby.
MAX_LOBBY_PLAYERS = 110

DEFAULT_TEAM_SIZE = 3


def _game_placement(session: dict) -> int | None:
    stats = session.get("trackedStats") or {}
    for key in PLACEMENT_KEYS:
        if key in stats:
            try:
                return int(float(stats[key]))
            except (TypeError, ValueError):
                return None
    return None


def count_game_wins(raw_stats: dict | None) -> int:
    """How many games this team won (in-game placement 1), from the per-game `sessionHistory` Osirion reports."""
    if not raw_stats:
        return 0
    return sum(1 for session in (raw_stats.get("sessionHistory") or []) if _game_placement(session) == 1)


def team_size(raw_stats: dict | None, default: int = DEFAULT_TEAM_SIZE) -> int:
    """Players on the team, from the leaderboard entry itself (solos 1, duos 2, trios 3, squads 4)."""
    players = (raw_stats or {}).get("players")
    if isinstance(players, list) and players:
        return len(players)
    return default


def per_player_win_value(total_pool: Decimal, win_share: Decimal, size: int) -> Decimal:
    """One game win's dividend pool for ONE member of the winning team."""
    size = max(1, int(size))
    return (total_pool * win_share / Decimal(size)).quantize(CENT, rounding=ROUND_DOWN)


def player_pool(raw_stats: dict | None, total_pool: Decimal, win_share: Decimal) -> Decimal:
    """The dividend pool for one player: their team's game wins x the per-player value of a win."""
    wins = count_game_wins(raw_stats)
    if wins <= 0:
        return Decimal("0.00")
    return per_player_win_value(total_pool, win_share, team_size(raw_stats)) * wins


def lobby_is_acceptable(players_first_page: int, total_pages: int) -> bool:
    """True if a leaderboard could be a set lobby of <= MAX_LOBBY_PLAYERS players. `players_first_page` is how many
    players the first page holds, `total_pages` how many pages exist. Only rejects when the field is SURELY too big
    (every page but the last is full, so players_first_page x (total_pages - 1) is a lower bound): an 80 / 78 / 100
    player lobby, however Osirion pages it, is accepted."""
    if total_pages <= 1:
        return players_first_page <= MAX_LOBBY_PLAYERS
    return players_first_page * (total_pages - 1) <= MAX_LOBBY_PLAYERS
