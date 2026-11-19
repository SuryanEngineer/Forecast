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


_inflight: dict[Hashable, threading.Event] = {}
_STALE_GRACE = 600.0  # an expired entry may still be served this long while one request recomputes it
_WAIT_SECONDS = 25.0


def cached_call(key: Hashable, seconds: float, compute: Callable[[], Any]) -> Any:
    """Single-flight: when an entry is missing/expired, ONE request recomputes it. Others in the meantime get the previous
    (stale) value straight away if there is one, otherwise wait for the leader's result instead of all hitting the database
    at once (a page that fires many requests on a cold cache used to run each query N times and exhaust the connection pool)."""
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        waiter = _inflight.get(key)
        leader = waiter is None
        if leader:
            _inflight[key] = threading.Event()
    if not leader:
        if hit is not None and now - hit[0] < _STALE_GRACE:
            return hit[1]
        waiter.wait(_WAIT_SECONDS)
        with _lock:
            again = _store.get(key)
        if again is not None:
            return again[1]
        return compute()  # the leader failed or took too long: do it ourselves
    try:
        value = compute()
        with _lock:
            if len(_store) >= _MAX_ENTRIES:
                stale = [k for k, (exp, _v) in _store.items() if exp <= now - _STALE_GRACE]
                for k in stale or list(_store)[: _MAX_ENTRIES // 2]:
                    _store.pop(k, None)
            _store[key] = (time.monotonic() + seconds, value)
        return value
    finally:
        with _lock:
            ev = _inflight.pop(key, None)
        if ev is not None:
            ev.set()


def clear() -> None:
    with _lock:
        _store.clear()
