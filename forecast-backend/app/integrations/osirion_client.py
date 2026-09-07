"""
Thin HTTP client for Osirion's public Fortnite tournament API
(https://fnapi.osirion.gg -- currently in beta, no API key required or
even available yet per the API's own docs as of Sept 2026; see
app/core/config.py's OSIRION_API_BASE_URL if that ever changes).

Only two endpoints exist and both are used here:
- GET /v1/tournaments -- tournament + event-window + score-location
  metadata (no live results). See `list_tournaments`.
- GET /v1/tournaments/leaderboard -- paginated placement data for one
  specific (leaderboardEventId, leaderboardEventWindowId) pair. See
  `get_leaderboard_page`.

This module deliberately returns plain dicts (Osirion's own JSON shape,
`metadata` fields are explicitly free-form/untyped in their spec) rather
than strict Pydantic models -- app/services/osirion_service.py is the
layer that picks out the specific fields it needs and is where any future
schema drift should be absorbed.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("forecast.osirion")


class OsirionApiError(Exception):
    """Raised for any non-2xx response or unexpected shape from Osirion.
    Callers (see osirion_service.py) should catch this per-tournament so
    one bad/rate-limited call doesn't take down an entire sync pass."""


def _get(path: str, params: dict) -> dict:
    url = f"{settings.OSIRION_API_BASE_URL}{path}"
    try:
        response = httpx.get(url, params=params, headers={"Accept": "application/json"}, timeout=15.0)
    except httpx.HTTPError as exc:
        raise OsirionApiError(f"network error calling Osirion {path}: {exc}") from exc

    if response.status_code >= 400:
        # Osirion's documented error shape is {success, errorCode,
        # errorMessage} -- fall back to the raw body if it's not that.
        try:
            body = response.json()
            detail = body.get("errorMessage") or body.get("errorCode") or body
        except Exception:
            detail = response.text
        raise OsirionApiError(f"Osirion {path} returned {response.status_code}: {detail}")

    try:
        return response.json()
    except Exception as exc:
        raise OsirionApiError(f"Osirion {path} returned non-JSON response") from exc


def list_tournaments(region: str | None = None, include_historic_data: bool = False) -> list[dict]:
    """Returns the raw list of `TournamentsDataTournament` dicts. Each has
    eventId/eventGroup/displayData/eventWindows/metadata -- see
    osirion_service.py for how these get turned into something an admin
    can pick a leaderboard from."""
    params: dict = {"includeHistoricData": str(include_historic_data).lower()}
    if region:
        params["region"] = region
    data = _get("/v1/tournaments", params)
    if not data.get("success", True):
        raise OsirionApiError(f"Osirion /v1/tournaments reported success=false: {data}")
    return data.get("tournaments", [])


def get_leaderboard_page(leaderboard_event_id: str, leaderboard_event_window_id: str, page: int = 0) -> dict:
    """Returns the raw `TournamentLeaderboard` dict for one page:
    {leaderboardEventId, leaderboardEventWindowId, page, totalPages,
    updatedAt, entries}. `entries` is a list of per-TEAM dicts (supports
    duos/squads): {teamId, players: [{accountId, username, flagToken}],
    pointsEarned, score, rank, percentile, sessionHistory,
    unscoredSessions}. Caller (osirion_service.sync_leaderboard) loops
    page -> page+1 while page < totalPages."""
    params = {
        "leaderboardEventId": leaderboard_event_id,
        "leaderboardEventWindowId": leaderboard_event_window_id,
        "page": page,
    }
    data = _get("/v1/tournaments/leaderboard", params)
    if not data.get("success", True):
        raise OsirionApiError(f"Osirion /v1/tournaments/leaderboard reported success=false: {data}")
    return data.get("leaderboard", {})
