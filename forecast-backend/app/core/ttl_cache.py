"""
A tiny in-process response cache for hot, public, user-independent read endpoints.

Dozens of browsers poll the same few endpoints (the market list, leaderboard, calendar) every 15-45 seconds, and each poll
used to run the same database queries again. Caching the finished response for a few seconds means a crowd costs about one
set of queries per window instead of one per person, with prices at most a few seconds stale.

Use it ONLY for results that do not depend on who is asking (no user-specific data). It is called from inside the endpoint
body (`return cached_call(key, seconds, lambda: ...)`) rather than wrapping the endpoint, so FastAPI still sees the
endpoint's real signature. Each process has its own cache (the app runs one instance, and a few seconds of staleness is
the whole point).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

_MAX_ENTRIES = 600
_lock = threading.Lock()
_store: dict[Hashable, tuple[float, Any]] = {}


def cached_call(key: Hashable, seconds: float, compute: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    value = compute()
    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            stale = [k for k, (exp, _v) in _store.items() if exp <= now]
            for k in stale or list(_store)[: _MAX_ENTRIES // 2]:
                _store.pop(k, None)
        _store[key] = (now + seconds, value)
    return value


def clear() -> None:
    with _lock:
        _store.clear()
