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
import threading
import time

import httpx

from app.core.config import settings

logger = logging.getLogger("forecast.osirion")


class OsirionApiError(Exception):
    """Raised for any non-2xx response or unexpected shape from Osirion.
    Callers (see osirion_service.py) should catch this per-tournament so
    one bad/rate-limited call doesn't take down an entire sync pass."""


class _RateLimiter:
    """Paces every outbound Osirion request to stay under their documented
    per-minute cap (settings.OSIRION_MAX_REQUESTS_PER_MINUTE), no matter
    how many tournaments/pages a caller asks for in a burst. A plain
    fixed-interval gate rather than a bursty token bucket, deliberately --
    Osirion is a public beta API with no key, so its limit may well be
    shared across every user of the API, not metered per-app, and evenly
    spacing requests is the most conservative way to avoid tripping it.

    Thread-safe: a sync pass runs on a worker thread (see
    app/main.py's asyncio.to_thread call), and an admin's manual
    "sync now" click can run concurrently on a request-handling thread --
    both need to share the same pacing clock."""

    def __init__(self, max_per_minute: int) -> None:
        self._min_interval = 60.0 / max(max_per_minute, 1)
        self._lock = threading.Lock()
        self._last_call_at: float = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call_at = time.monotonic()


_rate_limiter = _RateLimiter(settings.OSIRION_MAX_REQUESTS_PER_MINUTE)

# Retries a transient failure (network blip, 5xx, or an explicit 429) a
# few times with backoff before giving up -- Osirion is a public beta API
# and occasional hiccups/rate-limit bumps are expected, not exceptional.
# Callers still see a clean OsirionApiError if every retry is exhausted.
_MAX_ATTEMPTS = 4


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return 5.0
    try:
        return max(1.0, min(float(value), 30.0))
    except ValueError:
        return 5.0


def _get(path: str, params: dict) -> dict:
    url = f"{settings.OSIRION_API_BASE_URL}{path}"
    last_exc: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        _rate_limiter.wait()
        try:
            response = httpx.get(url, params=params, headers={"Accept": "application/json"}, timeout=15.0)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(2**attempt)
                continue
            raise OsirionApiError(f"network error calling Osirion {path}: {exc}") from exc

        if response.status_code == 429 and attempt < _MAX_ATTEMPTS - 1:
            wait_s = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "Osirion rate-limited us on %s (attempt %d/%d) -- waiting %.1fs before retrying",
                path, attempt + 1, _MAX_ATTEMPTS, wait_s,
            )
            time.sleep(wait_s)
            continue

        if response.status_code >= 500 and attempt < _MAX_ATTEMPTS - 1:
            time.sleep(2**attempt)
            continue

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

    # Unreachable in practice (the loop above always returns or raises on
    # its last attempt), but fail loudly instead of implicitly returning
    # None if this retry logic is ever changed carelessly.
    raise OsirionApiError(f"Osirion {path} failed after {_MAX_ATTEMPTS} attempts") from last_exc


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
