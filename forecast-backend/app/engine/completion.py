"""
When is a tournament REALLY over? Pure functions (no database, no network).

Osirion's window end time is when the lobbies CLOSE, not when the last game finishes: games started before the close keep
running, and a final can run longer than its window says. Paying out (or announcing "ended") at the close time can therefore
happen while games are still being played. So:

  * SET LOBBY (a final / finals-sized field) with a known game count (the window's `matchCap`): the tournament is over when
    the LAST game has a winner -- and every game before it has one too. 'Game 10 of 10 has a winner', not a clock.
  * SET LOBBY with no published game count: over once the window has closed AND nobody has finished a game for a while.
  * OPEN round: lobbies close at the window end; games already started finish shortly after, so over = close + a short grace.
  * A safety valve: long after the close with no game activity at all, the tournament is treated as over (a cancelled or
    abandoned game must not leave it unpaid forever).

A game is identified by Osirion's `sessionId` (one id shared by every team in that game) and numbered by when it ended;
its winner is a team whose in-game placement in that session is 1 (see engine/performance_eval.py for the stat keys).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.engine.performance_eval import _game_placement

OPEN_GRACE = timedelta(minutes=45)    # after an open round's lobbies close: games already started can still finish
QUIET = timedelta(minutes=30)         # no game finished for this long (after the close) = the set lobby is done
SAFETY_QUIET = timedelta(minutes=60)  # safety valve: this long without any game ending ...
SAFETY_AFTER_CLOSE = timedelta(hours=3)  # ... and this long after the close = over regardless
NO_GAMES_AFTER_CLOSE = timedelta(hours=2)  # a closed set lobby that never produced a single game


def _parse(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class GameProgress:
    games_seen: int = 0            # distinct games with at least one result
    games_done: int = 0            # games 1..n ALL have a winner (n = this number)
    last_game_end: datetime | None = None   # when the most recent game ended (any team)
    last_winner_end: datetime | None = None  # when the latest game WITH a winner ended
    winners_by_game: tuple = ()    # (game number, ended_at iso or None, has_winner)


def analyze_games(entries: Iterable[dict]) -> GameProgress:
    """Progress from the leaderboard entries (each has `sessionHistory`: that team's games, with `endTime`, `sessionId` and
    `trackedStats` carrying the in-game placement)."""
    sessions: dict[str, dict] = {}
    for entry in entries:
        for i, session in enumerate((entry or {}).get("sessionHistory") or []):
            key = str(session.get("sessionId") or f"idx{i}")
            slot = sessions.setdefault(key, {"ended": None, "winner": False})
            ended = _parse(session.get("endTime"))
            if ended is not None and (slot["ended"] is None or ended < slot["ended"]):
                slot["ended"] = ended
            if _game_placement(session) == 1:
                slot["winner"] = True
    if not sessions:
        return GameProgress()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    ordered = sorted(sessions.items(), key=lambda kv: (kv[1]["ended"] is None, kv[1]["ended"] or epoch, kv[0]))
    done = 0
    for _, slot in ordered:
        if slot["winner"]:
            done += 1
        else:
            break
    ends = [s["ended"] for _, s in ordered if s["ended"] is not None]
    win_ends = [s["ended"] for _, s in ordered if s["winner"] and s["ended"] is not None]
    return GameProgress(
        games_seen=len(ordered),
        games_done=done,
        last_game_end=max(ends) if ends else None,
        last_winner_end=max(win_ends) if win_ends else None,
        winners_by_game=tuple((n, s["ended"].isoformat() if s["ended"] else None, s["winner"]) for n, (_, s) in enumerate(ordered, start=1)),
    )


@dataclass
class Verdict:
    over: bool
    over_at: datetime | None   # when it actually finished (last game's end / lobby close), when over
    reason: str


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def decide_over(
    *, now: datetime, window_end: datetime | None, lobby: str | None, expected_games: int | None, progress: GameProgress
) -> Verdict:
    """Is the tournament over? `lobby` is 'open' / 'set' / None (unknown, treated like a set lobby)."""
    now, window_end = _aware(now), _aware(window_end)
    quiet_for = (now - progress.last_game_end) if progress.last_game_end else None

    if lobby == "open":
        if window_end is None:
            return Verdict(False, None, "open round with no close time")
        if now >= window_end + OPEN_GRACE:
            return Verdict(True, window_end, "lobbies closed and the last games have had time to finish")
        return Verdict(False, None, "lobbies are still open or closed too recently for the last games to finish")

    if expected_games and expected_games > 0:
        if progress.games_done >= expected_games:
            return Verdict(True, progress.last_winner_end or progress.last_game_end or window_end, f"game {expected_games} of {expected_games} has a winner")
        if window_end is not None and now >= window_end + SAFETY_AFTER_CLOSE and (quiet_for is None or quiet_for >= SAFETY_QUIET):
            return Verdict(True, progress.last_game_end or window_end, f"only {progress.games_done} of {expected_games} games finished, but nothing has been played for an hour and the window closed 3h ago")
        return Verdict(False, None, f"{progress.games_done} of {expected_games} games have a winner")

    # No published game count: wait for the window to close, then for the games to stop.
    if window_end is None or now < window_end:
        return Verdict(False, None, "window still open")
    if progress.games_seen == 0:
        if now >= window_end + NO_GAMES_AFTER_CLOSE:
            return Verdict(True, window_end, "closed with no games recorded")
        return Verdict(False, None, "closed, waiting for results")
    if quiet_for is not None and quiet_for >= QUIET:
        return Verdict(True, progress.last_game_end, "no game has finished for 30 minutes after the close")
    return Verdict(False, None, "games still finishing after the close")
